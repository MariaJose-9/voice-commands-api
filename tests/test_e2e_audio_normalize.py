from __future__ import annotations

from pathlib import Path
import importlib

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.audio.schemas import AudioTranscriptionResponse
from app.config import MAX_AUDIO_FILE_MB
from app.schemas import CommandName


audio_router_module = importlib.import_module("app.audio.router")
client = TestClient(main_module.app)


def _mock_audio_normalize(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    transcribed_text: str,
) -> list[Path]:
    temp_path = tmp_path / "mock-audio.mp3"
    temp_path.write_bytes(b"fake-audio")
    cleaned: list[Path] = []

    monkeypatch.setattr(
        audio_router_module,
        "save_upload_file_to_temp",
        lambda upload: (temp_path, 10),
    )
    monkeypatch.setattr(
        audio_router_module,
        "transcribe_audio_file",
        lambda path, language_hint=None: AudioTranscriptionResponse(
            ok=True,
            text=transcribed_text,
            language=language_hint or "es",
            duration_seconds=1.0,
            engine="faster_whisper",
            model="mock",
            segments=[
                {
                    "start": 0.0,
                    "end": 1.0,
                    "text": transcribed_text,
                }
            ],
        ),
    )
    monkeypatch.setattr(audio_router_module, "save_normalization_log", lambda **kwargs: None)
    monkeypatch.setattr(audio_router_module, "save_audio_transcription_log", lambda **kwargs: None)
    monkeypatch.setattr(audio_router_module, "cleanup_temp_file", lambda path: cleaned.append(path))
    return cleaned


def _assert_expected_commands(actual: list[dict], expected: list[dict]) -> None:
    actual_commands = [item["command"] for item in actual]
    assert CommandName.UNKNOWN.value not in actual_commands

    for expected_command in expected:
        matches = [
            command
            for command in actual
            if command["command"] == expected_command["command"]
        ]
        assert matches, {"missing": expected_command, "actual": actual}

        for entity_key in ("monitor", "layout", "size_inches"):
            if entity_key not in expected_command:
                continue
            assert any(
                command.get(entity_key) == expected_command[entity_key]
                for command in matches
            ), {
                "missing_entity": expected_command,
                "actual_matches": matches,
            }


@pytest.mark.parametrize(
    ("transcribed_text", "expected"),
    [
        (
            "pantalla 2 mueve la la derecha y luego las es en el tamaño de 55 puladas",
            [
                {"command": CommandName.SELECT_MONITOR.value, "monitor": 2},
                {"command": CommandName.MOVE_RIGHT.value},
                {"command": CommandName.SET_SIZE.value, "size_inches": 55},
            ],
        ),
        (
            "coja la pantalla una y mueve la licuada",
            [
                {"command": CommandName.SELECT_MONITOR.value, "monitor": 1},
                {"command": CommandName.MOVE_LEFT.value},
            ],
        ),
        (
            "hazlo un poco mas grande",
            [{"command": CommandName.INCREASE_SIZE.value}],
        ),
    ],
)
def test_e2e_audio_normalize_critical_transcriptions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    transcribed_text: str,
    expected: list[dict],
) -> None:
    cleaned = _mock_audio_normalize(monkeypatch, tmp_path, transcribed_text)

    response = client.post(
        "/v1/audio/normalize",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
        data={"language_hint": "es"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["transcription"]["text"] == transcribed_text
    _assert_expected_commands(payload["normalization"]["commands"], expected)
    assert cleaned == [tmp_path / "mock-audio.mp3"]


def test_e2e_audio_normalize_invalid_extension_returns_400() -> None:
    response = client.post(
        "/v1/audio/normalize",
        files={"file": ("sample.exe", b"fake-audio", "application/octet-stream")},
        data={"language_hint": "es"},
    )

    assert response.status_code == 400
    assert "Unsupported audio file extension" in response.json()["detail"]


def test_e2e_audio_normalize_too_large_returns_413() -> None:
    oversized_payload = b"0" * (MAX_AUDIO_FILE_MB * 1024 * 1024 + 1)

    response = client.post(
        "/v1/audio/normalize",
        files={"file": ("sample.mp3", oversized_payload, "audio/mpeg")},
        data={"language_hint": "es"},
    )

    assert response.status_code == 413
    assert "maximum size" in response.json()["detail"]
