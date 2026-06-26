"""Persistent logging for audio transcription metadata."""

from __future__ import annotations

import logging
from typing import Optional

from app.config import ENABLE_AUDIO_TRANSCRIPTION_LOGS
from app.db.models import AudioTranscriptionLog
from app.db.session import Session as SessionFactory, engine


logger = logging.getLogger(__name__)


def save_audio_transcription_log(
    *,
    filename: Optional[str],
    content_type: Optional[str],
    size_bytes: Optional[int],
    language_hint: Optional[str],
    detected_language: Optional[str],
    transcribed_text: Optional[str],
    duration_seconds: Optional[float],
    engine_name: str,
    model_name: str,
    ok: bool = True,
    error_message: Optional[str] = None,
    used_for_normalization: bool = False,
) -> None:
    """Persist audio transcription metadata without storing the audio file itself."""

    if not ENABLE_AUDIO_TRANSCRIPTION_LOGS:
        return
    if SessionFactory is None or engine is None:
        return

    try:
        with SessionFactory(engine) as session:
            session.add(
                AudioTranscriptionLog(
                    filename=filename,
                    content_type=content_type,
                    size_bytes=size_bytes,
                    language_hint=language_hint,
                    detected_language=detected_language,
                    transcribed_text=transcribed_text,
                    duration_seconds=duration_seconds,
                    engine=engine_name,
                    model=model_name,
                    ok=ok,
                    error_message=error_message,
                    used_for_normalization=used_for_normalization,
                )
            )
            session.commit()
    except Exception:
        logger.warning(
            "Failed to persist audio transcription log",
            extra={"event": "audio_transcription_log_warning"},
            exc_info=True,
        )
