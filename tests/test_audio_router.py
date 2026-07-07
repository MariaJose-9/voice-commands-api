from __future__ import annotations

from pathlib import Path
import importlib

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.audio.schemas import AudioTranscriptionResponse
from app.schemas import CommandName


audio_router_module = importlib.import_module("app.audio.router")
client = TestClient(main_module.app)


def test_audio_status_endpoint() -> None:
    response = client.get("/v1/audio/status")
    assert response.status_code == 200
    payload = response.json()
    assert "enabled" in payload
    assert "engine" in payload
    assert "allowed_extensions" in payload


def test_audio_status_endpoint_uses_runtime_effective_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        audio_router_module,
        "get_effective_transcription_settings",
        lambda: {
            "enabled": True,
            "engine": "faster_whisper",
            "model_name": "tiny",
            "device": "cpu",
            "compute_type": "int8",
            "allowed_extensions": [".ogg"],
            "max_file_mb": 7,
            "max_duration_seconds": 12,
        },
    )
    monkeypatch.setattr(audio_router_module, "is_transcription_model_loaded", lambda: True)
    monkeypatch.setattr(
        audio_router_module,
        "_catalog_runtime_status",
        lambda: (3, True),
    )
    monkeypatch.setattr(
        audio_router_module,
        "get_bool_setting",
        lambda key, default: True,
    )

    response = client.get("/v1/audio/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model"] == "tiny"
    assert payload["allowed_extensions"] == [".ogg"]
    assert payload["max_file_mb"] == 7
    assert payload["semantic_matcher_enabled"] is True
    assert payload["active_catalog_version"] == 3
    assert payload["catalog_dirty"] is True


def test_openapi_contains_audio_routes() -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200
    payload = response.json()
    assert "/v1/audio/transcribe" in payload["paths"]
    assert "/v1/audio/normalize" in payload["paths"]


def test_audio_transcribe_missing_file_returns_422() -> None:
    response = client.post("/v1/audio/transcribe", data={})
    assert response.status_code == 422


def test_audio_transcribe_invalid_extension_returns_400() -> None:
    response = client.post(
        "/v1/audio/transcribe",
        files={"file": ("sample.exe", b"fake-audio", "application/octet-stream")},
    )
    assert response.status_code == 400
    assert "Unsupported audio file extension" in response.json()["detail"]


def test_audio_transcribe_calls_mocked_service(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    temp_path = tmp_path / "audio.mp3"
    temp_path.write_bytes(b"fake-audio")
    cleaned: list[Path] = []

    monkeypatch.setattr(audio_router_module, "save_upload_file_to_temp", lambda upload: (temp_path, 10))
    monkeypatch.setattr(
        audio_router_module,
        "transcribe_audio_file",
        lambda path, language_hint=None: AudioTranscriptionResponse(
            ok=True,
            text="monitor two and zoom in",
            language=language_hint or "en",
            duration_seconds=1.2,
            engine="faster_whisper",
            model="base",
            segments=[],
        ),
    )
    monkeypatch.setattr(audio_router_module, "save_audio_transcription_log", lambda **kwargs: None)
    monkeypatch.setattr(audio_router_module, "cleanup_temp_file", lambda path: cleaned.append(path))

    response = client.post(
        "/v1/audio/transcribe",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
        data={"language_hint": "en"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["text"] == "monitor two and zoom in"
    assert cleaned == [temp_path]


def test_audio_normalize_calls_transcription_and_real_normalizer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    temp_path = tmp_path / "audio.mp3"
    temp_path.write_bytes(b"fake-audio")

    monkeypatch.setattr(audio_router_module, "save_upload_file_to_temp", lambda upload: (temp_path, 10))
    monkeypatch.setattr(
        audio_router_module,
        "transcribe_audio_file",
        lambda path, language_hint=None: AudioTranscriptionResponse(
            ok=True,
            text="monitor two and zoom in",
            language="en",
            duration_seconds=1.2,
            engine="faster_whisper",
            model="base",
            segments=[],
        ),
    )
    monkeypatch.setattr(audio_router_module, "save_normalization_log", lambda **kwargs: None)
    monkeypatch.setattr(audio_router_module, "save_audio_transcription_log", lambda **kwargs: None)
    monkeypatch.setattr(audio_router_module, "cleanup_temp_file", lambda path: None)

    response = client.post(
        "/v1/audio/normalize",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
        data={"language_hint": "en"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcription"]["text"] == "monitor two and zoom in"
    assert [command["command"] for command in payload["normalization"]["commands"]] == [
        CommandName.SELECT_MONITOR.value,
        CommandName.ZOOM_IN.value,
    ]


def test_audio_temp_file_is_cleaned_when_transcription_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    temp_path = tmp_path / "audio.mp3"
    temp_path.write_bytes(b"fake-audio")
    cleaned: list[Path] = []

    monkeypatch.setattr(audio_router_module, "save_upload_file_to_temp", lambda upload: (temp_path, 10))

    def raise_error(path, language_hint=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(audio_router_module, "transcribe_audio_file", raise_error)
    monkeypatch.setattr(audio_router_module, "save_audio_transcription_log", lambda **kwargs: None)
    monkeypatch.setattr(audio_router_module, "cleanup_temp_file", lambda path: cleaned.append(path))

    response = client.post(
        "/v1/audio/transcribe",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
    )

    assert response.status_code == 500
    assert cleaned == [temp_path]


def test_audio_transcribe_endpoint_survives_log_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    temp_path = tmp_path / "audio.mp3"
    temp_path.write_bytes(b"fake-audio")

    monkeypatch.setattr(audio_router_module, "save_upload_file_to_temp", lambda upload: (temp_path, 10))
    monkeypatch.setattr(
        audio_router_module,
        "transcribe_audio_file",
        lambda path, language_hint=None: AudioTranscriptionResponse(
            ok=True,
            text="monitor two",
            language="en",
            duration_seconds=1.0,
            engine="faster_whisper",
            model="base",
            segments=[],
        ),
    )
    monkeypatch.setattr(
        audio_router_module,
        "save_audio_transcription_log",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    monkeypatch.setattr(audio_router_module, "cleanup_temp_file", lambda path: None)

    response = client.post(
        "/v1/audio/transcribe",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
    )

    assert response.status_code == 200
    assert response.json()["text"] == "monitor two"
