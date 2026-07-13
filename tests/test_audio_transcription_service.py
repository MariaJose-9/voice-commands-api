from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.audio.transcription_service as transcription_service
import app.services.runtime_settings_service as runtime_settings_service
from app.audio.providers.faster_whisper_provider import FasterWhisperProvider
from app.db.models import AppSetting


class _FakeWhisperModel:
    init_calls = 0
    transcribe_calls = []

    def __init__(self, model_name: str, *, device: str, compute_type: str) -> None:
        type(self).init_calls += 1
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type

    def transcribe(self, file_path: str, *, beam_size: int, language, vad_filter: bool):
        type(self).transcribe_calls.append(
            {
                "file_path": file_path,
                "beam_size": beam_size,
                "language": language,
                "vad_filter": vad_filter,
            }
        )
        segments = [
            SimpleNamespace(start=0.0, end=0.8, text="monitor two"),
            SimpleNamespace(start=0.8, end=1.6, text="zoom in"),
        ]
        info = SimpleNamespace(language="en", duration=1.6)
        return segments, info


def _install_fake_faster_whisper(monkeypatch) -> None:
    fake_module = SimpleNamespace(WhisperModel=_FakeWhisperModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)


def _reset_service_state(monkeypatch) -> None:
    monkeypatch.setattr(transcription_service, "_provider", None)
    monkeypatch.setattr(transcription_service, "_provider_signature", None)
    _FakeWhisperModel.init_calls = 0
    _FakeWhisperModel.transcribe_calls = []


def test_faster_whisper_provider_mocked_loads_once(monkeypatch) -> None:
    _install_fake_faster_whisper(monkeypatch)
    settings = {
        "model_name": "base",
        "device": "cpu",
        "compute_type": "int8",
        "beam_size": 1,
        "language_default": "",
        "vad_filter": False,
        "max_duration_seconds": 30,
    }
    _FakeWhisperModel.init_calls = 0

    provider = FasterWhisperProvider(settings)
    model_one = provider.load()
    model_two = provider.load()

    assert model_one is model_two
    assert _FakeWhisperModel.init_calls == 1
    assert provider.is_loaded() is True


def test_transcription_service_selects_faster_whisper(monkeypatch) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")

    provider = transcription_service.get_transcription_provider()

    assert isinstance(provider, FasterWhisperProvider)
    assert provider.name == "faster_whisper"


def test_lazy_loading_loads_model_once(monkeypatch) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")

    model_one = transcription_service.get_transcription_model()
    model_two = transcription_service.get_transcription_model()

    assert model_one is model_two
    assert _FakeWhisperModel.init_calls == 1


def test_warmup_returns_loaded_true(monkeypatch) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")

    response = transcription_service.warmup_transcription_model()

    assert response.loaded is True
    assert response.engine == "faster_whisper"


def test_transcribe_audio_file_concatenates_segments(monkeypatch, tmp_path) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")
    monkeypatch.setattr(transcription_service, "MAX_AUDIO_DURATION_SECONDS", 30)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")

    response = transcription_service.transcribe_audio_file(audio_path)

    assert response.ok is True
    assert response.text == "monitor two zoom in"
    assert response.language == "en"
    assert len(response.segments) == 2


def test_transcribe_audio_file_passes_language_hint(monkeypatch, tmp_path) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")

    transcription_service.transcribe_audio_file(audio_path, language_hint="es")

    assert _FakeWhisperModel.transcribe_calls[-1]["language"] == "es"


def test_transcribe_audio_file_treats_auto_language_hint_as_autodetect(
    monkeypatch,
    tmp_path,
) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")

    transcription_service.transcribe_audio_file(audio_path, language_hint="auto")

    assert _FakeWhisperModel.transcribe_calls[-1]["language"] is None


def test_transcribe_audio_file_treats_auto_default_language_as_autodetect(
    monkeypatch,
    tmp_path,
) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")
    monkeypatch.setattr(
        runtime_settings_service,
        "get_audio_str_setting",
        lambda key, default: "auto" if key == "TRANSCRIPTION_LANGUAGE_DEFAULT" else default,
    )
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")

    transcription_service.transcribe_audio_file(audio_path)

    assert _FakeWhisperModel.transcribe_calls[-1]["language"] is None


def test_transcribe_audio_file_converts_to_wav_when_direct_decode_fails(
    monkeypatch,
    tmp_path,
) -> None:
    class _DecodeFailsUntilWavModel(_FakeWhisperModel):
        def transcribe(self, file_path: str, *, beam_size: int, language, vad_filter: bool):
            type(self).transcribe_calls.append(
                {
                    "file_path": file_path,
                    "beam_size": beam_size,
                    "language": language,
                    "vad_filter": vad_filter,
                }
            )
            if not file_path.endswith(".wav"):
                raise RuntimeError("invalid mp4 codec")
            segments = [SimpleNamespace(start=0.0, end=1.0, text="monitor one")]
            info = SimpleNamespace(language="en", duration=1.0)
            return segments, info

    def fake_run(command, check, capture_output, text, timeout):
        output_path = Path(command[-1])
        output_path.write_bytes(b"fake-wav")
        return SimpleNamespace(returncode=0, stderr="")

    fake_module = SimpleNamespace(WhisperModel=_DecodeFailsUntilWavModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(
        "app.audio.providers.faster_whisper_provider.subprocess.run",
        fake_run,
    )
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")
    audio_path = tmp_path / "sample.mp4"
    audio_path.write_bytes(b"fake-mp4")

    response = transcription_service.transcribe_audio_file(audio_path)

    assert response.text == "monitor one"
    calls = _DecodeFailsUntilWavModel.transcribe_calls
    assert calls[0]["file_path"].endswith("sample.mp4")
    assert calls[1]["file_path"].endswith(".wav")
    assert not Path(calls[1]["file_path"]).exists()


def test_transcribe_audio_file_reports_conversion_failure(
    monkeypatch,
    tmp_path,
) -> None:
    class _AlwaysFailsModel(_FakeWhisperModel):
        def transcribe(self, file_path: str, *, beam_size: int, language, vad_filter: bool):
            raise RuntimeError("decode failed")

    def fake_run(command, check, capture_output, text, timeout):
        return SimpleNamespace(returncode=1, stderr="unsupported codec")

    fake_module = SimpleNamespace(WhisperModel=_AlwaysFailsModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    monkeypatch.setattr(
        "app.audio.providers.faster_whisper_provider.subprocess.run",
        fake_run,
    )
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")
    audio_path = tmp_path / "sample.mp4"
    audio_path.write_bytes(b"fake-mp4")

    with pytest.raises(RuntimeError, match="unsupported codec"):
        transcription_service.transcribe_audio_file(audio_path)


def test_get_transcription_model_fails_when_disabled(monkeypatch) -> None:
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", False)

    with pytest.raises(RuntimeError, match="Audio transcription is disabled"):
        transcription_service.get_transcription_model()


def test_unsupported_engine_fails_clearly(monkeypatch) -> None:
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "openai")

    with pytest.raises(RuntimeError, match="Unsupported transcription engine: openai"):
        transcription_service.get_transcription_provider()


def test_transcribe_audio_file_fails_when_duration_exceeds_max(monkeypatch, tmp_path) -> None:
    class _LongAudioModel(_FakeWhisperModel):
        def transcribe(self, file_path: str, *, beam_size: int, language, vad_filter: bool):
            segments = [SimpleNamespace(start=0.0, end=40.0, text="very long audio")]
            info = SimpleNamespace(language="en", duration=40.0)
            return segments, info

    fake_module = SimpleNamespace(WhisperModel=_LongAudioModel)
    monkeypatch.setitem(sys.modules, "faster_whisper", fake_module)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(transcription_service, "ENABLE_AUDIO_TRANSCRIPTION", True)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_ENGINE", "faster_whisper")
    monkeypatch.setattr(transcription_service, "MAX_AUDIO_DURATION_SECONDS", 30)
    audio_path = tmp_path / "sample.mp3"
    audio_path.write_bytes(b"fake-audio")

    with pytest.raises(ValueError, match="Audio duration exceeds maximum"):
        transcription_service.transcribe_audio_file(audio_path)


def test_db_setting_overrides_transcription_model_name(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AppSetting(key="TRANSCRIPTION_MODEL_NAME", value="tiny"))
        session.commit()

    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(runtime_settings_service, "SessionFactory", Session)
    monkeypatch.setattr(runtime_settings_service, "engine", engine)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_MODEL_NAME", "base")

    model = transcription_service.get_transcription_model()

    assert model.model_name == "tiny"


def test_db_unavailable_uses_config_default_for_transcription_model(monkeypatch) -> None:
    _install_fake_faster_whisper(monkeypatch)
    _reset_service_state(monkeypatch)
    monkeypatch.setattr(runtime_settings_service, "SessionFactory", None)
    monkeypatch.setattr(runtime_settings_service, "engine", None)
    monkeypatch.setattr(transcription_service, "TRANSCRIPTION_MODEL_NAME", "base")

    model = transcription_service.get_transcription_model()

    assert model.model_name == "base"
