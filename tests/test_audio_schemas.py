from __future__ import annotations

from app.audio.schemas import (
    AudioNormalizeResponse,
    AudioSegment,
    AudioStatusResponse,
    AudioTranscriptionResponse,
)
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand


def test_audio_transcription_response_instantiates() -> None:
    response = AudioTranscriptionResponse(
        ok=True,
        text="monitor two and zoom in",
        language="en",
        duration_seconds=2.34,
        engine="faster_whisper",
        model="base",
        segments=[
            AudioSegment(start=0.0, end=1.02, text="monitor two"),
            AudioSegment(start=1.02, end=2.34, text="and zoom in"),
        ],
    )

    assert response.ok is True
    assert response.engine == "faster_whisper"
    assert len(response.segments) == 2


def test_audio_normalize_response_accepts_normalize_response() -> None:
    normalization = NormalizeResponse(
        ok=True,
        raw_text="monitor two and zoom in",
        normalized_text="monitor two and zoom in",
        language="en",
        commands=[
            NormalizedCommand(
                command=CommandName.SELECT_MONITOR,
                confidence=1.0,
                method=MatchMethod.entity_rule,
                monitor=2,
                raw_fragment="monitor two",
            )
        ],
        needs_confirmation=False,
        message=None,
    )
    transcription = AudioTranscriptionResponse(
        ok=True,
        text="monitor two and zoom in",
        language="en",
        duration_seconds=2.34,
        engine="faster_whisper",
        model="base",
        segments=[],
    )

    response = AudioNormalizeResponse(
        ok=True,
        transcription=transcription,
        normalization=normalization,
    )

    assert response.normalization.commands[0].command == CommandName.SELECT_MONITOR
    assert response.transcription.model == "base"


def test_audio_status_response_model_dump() -> None:
    response = AudioStatusResponse(
        enabled=True,
        engine="faster_whisper",
        model="base",
        device="cpu",
        compute_type="int8",
        model_loaded=False,
        allowed_extensions=[".ogg", ".mp3"],
        max_file_mb=10,
        max_duration_seconds=30,
        semantic_matcher_enabled=True,
        active_catalog_version=1,
        catalog_dirty=False,
    )

    dumped = response.model_dump()

    assert dumped["engine"] == "faster_whisper"
    assert dumped["allowed_extensions"] == [".ogg", ".mp3"]
    assert dumped["max_file_mb"] == 10
    assert dumped["semantic_matcher_enabled"] is True
    assert dumped["active_catalog_version"] == 1
