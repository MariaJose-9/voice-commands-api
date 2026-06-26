from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.audio.log_service as audio_log_service
from app.db.models import AudioTranscriptionLog


def test_save_audio_transcription_log_creates_row(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(audio_log_service, "SessionFactory", Session)
    monkeypatch.setattr(audio_log_service, "engine", engine)
    monkeypatch.setattr(audio_log_service, "ENABLE_AUDIO_TRANSCRIPTION_LOGS", True)

    audio_log_service.save_audio_transcription_log(
        filename="sample.mp3",
        content_type="audio/mpeg",
        size_bytes=1234,
        language_hint="en",
        detected_language="en",
        transcribed_text="monitor two",
        duration_seconds=1.2,
        engine_name="faster_whisper",
        model_name="base",
        ok=True,
        error_message=None,
        used_for_normalization=False,
    )

    with Session(engine) as session:
        row = session.exec(select(AudioTranscriptionLog)).first()
        assert row is not None
        assert row.filename == "sample.mp3"
        assert row.engine == "faster_whisper"
        assert row.ok is True
