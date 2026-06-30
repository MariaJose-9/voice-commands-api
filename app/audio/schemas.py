"""Pydantic schemas for audio transcription and normalization."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas import NormalizeResponse


class AudioSegment(BaseModel):
    """Single transcription segment with timing metadata."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "start": 0.0,
                "end": 1.42,
                "text": "monitor two",
            }
        }
    )

    start: float = Field(..., description="Segment start in seconds.")
    end: float = Field(..., description="Segment end in seconds.")
    text: str = Field(..., description="Transcribed segment text.")


class AudioTranscriptionResponse(BaseModel):
    """Response payload for raw audio transcription."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "text": "monitor two and zoom in",
                "language": "en",
                "duration_seconds": 2.34,
                "engine": "faster_whisper",
                "model": "base",
                "segments": [
                    {"start": 0.0, "end": 1.02, "text": "monitor two"},
                    {"start": 1.02, "end": 2.34, "text": "and zoom in"},
                ],
                "message": None,
            }
        }
    )

    ok: bool
    text: str
    language: Optional[str] = None
    duration_seconds: Optional[float] = None
    engine: str
    model: str
    segments: list[AudioSegment]
    message: Optional[str] = None


class AudioNormalizeResponse(BaseModel):
    """Response payload for audio transcription plus command normalization."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "transcription": {
                    "ok": True,
                    "text": "monitor two and zoom in",
                    "language": "en",
                    "duration_seconds": 2.34,
                    "engine": "faster_whisper",
                    "model": "base",
                    "segments": [
                        {"start": 0.0, "end": 1.02, "text": "monitor two"},
                        {"start": 1.02, "end": 2.34, "text": "and zoom in"},
                    ],
                    "message": None,
                },
                "normalization": {
                    "ok": True,
                    "raw_text": "monitor two and zoom in",
                    "normalized_text": "monitor two and zoom in",
                    "language": "en",
                    "commands": [
                        {
                            "command": "SELECT_MONITOR",
                            "confidence": 1.0,
                            "method": "entity_rule",
                            "monitor": 2,
                            "layout": None,
                            "size_inches": None,
                            "value": None,
                            "raw_fragment": "monitor two",
                        }
                    ],
                    "needs_confirmation": False,
                    "message": None,
                },
                "message": None,
            }
        }
    )

    ok: bool
    transcription: AudioTranscriptionResponse
    normalization: NormalizeResponse
    message: Optional[str] = None


class AudioStatusResponse(BaseModel):
    """Operational status for the audio transcription subsystem."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enabled": True,
                "engine": "faster_whisper",
                "model": "base",
                "device": "cpu",
                "compute_type": "int8",
                "model_loaded": False,
                "allowed_extensions": [".ogg", ".mp3", ".m4a"],
                "max_file_mb": 10,
                "max_duration_seconds": 30,
                "semantic_matcher_enabled": True,
                "active_catalog_version": 1,
                "catalog_dirty": False,
            }
        }
    )

    enabled: bool
    engine: str
    model: str
    device: str
    compute_type: str
    model_loaded: bool
    allowed_extensions: list[str]
    max_file_mb: int
    max_duration_seconds: int
    semantic_matcher_enabled: bool = False
    active_catalog_version: Optional[int] = None
    catalog_dirty: bool = False


class AudioWarmupResponse(BaseModel):
    """Response payload for manual warmup of the audio transcription model."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "enabled": True,
                "loaded": True,
                "engine": "faster_whisper",
                "model": "base",
                "message": None,
            }
        }
    )

    enabled: bool
    loaded: bool
    engine: str
    model: str
    message: Optional[str] = None
