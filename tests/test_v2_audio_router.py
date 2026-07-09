from __future__ import annotations

from pathlib import Path
import importlib

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.audio.schemas import AudioTranscriptionResponse
from app.schemas import CommandName
from app.v2.schemas import DynamicCommand, NormalizeV2Response


audio_router_module = importlib.import_module("app.audio.router")
client = TestClient(main_module.app)


def test_v2_audio_normalize_returns_custom_dynamic_command(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    temp_path = tmp_path / "audio.mp3"
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
            text="rota el monitor dos noventa grados",
            language=language_hint or "es",
            duration_seconds=1.0,
            engine="faster_whisper",
            model="mock",
            segments=[],
        ),
    )
    monkeypatch.setattr(
        audio_router_module,
        "normalize_command_text_v2",
        lambda text, language_hint=None, context=None, client_capabilities=None: NormalizeV2Response(
            ok=True,
            raw_text=text,
            normalized_text=text,
            language=language_hint,
            commands=[
                DynamicCommand(
                    code="ROTATE_SCREEN",
                    type="custom",
                    client_action_key="rotate_screen",
                    confidence=0.92,
                    method="llm",
                    params={"monitor": 2, "angle": 90},
                    raw_fragment=text,
                )
            ],
            needs_confirmation=False,
        ),
    )
    monkeypatch.setattr(audio_router_module, "save_audio_transcription_log", lambda **kwargs: None)
    monkeypatch.setattr(audio_router_module, "cleanup_temp_file", lambda path: cleaned.append(path))

    response = client.post(
        "/v2/audio/normalize",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
        data={
            "language_hint": "es",
            "client_capabilities_json": '["rotate_screen"]',
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["transcription"]["text"] == "rota el monitor dos noventa grados"
    command = payload["normalization"]["commands"][0]
    assert command["code"] == "ROTATE_SCREEN"
    assert command["type"] == "custom"
    assert command["client_action_key"] == "rotate_screen"
    assert command["params"] == {"monitor": 2, "angle": 90}
    assert cleaned == [temp_path]


def test_v2_audio_normalize_requires_token_when_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_module, "API_AUTH_TOKEN", "secret-token")

    response = client.post(
        "/v2/audio/normalize",
        files={"file": ("sample.mp3", b"fake-audio", "audio/mpeg")},
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API token."}


def test_v1_audio_normalize_still_works(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    temp_path = tmp_path / "audio.mp3"
    temp_path.write_bytes(b"fake-audio")

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
            text="monitor two and zoom in",
            language="en",
            duration_seconds=1.0,
            engine="faster_whisper",
            model="mock",
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
    commands = response.json()["normalization"]["commands"]
    assert [command["command"] for command in commands] == [
        CommandName.SELECT_MONITOR.value,
        CommandName.ZOOM_IN.value,
    ]
