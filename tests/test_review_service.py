from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AppSetting,
    AudioTranscriptionLog,
    CommandDefinition,
    CommandExample,
    CommandName,
    ExampleSource,
    MatchType,
    NormalizationLog,
    ReviewStatus,
)
from app.services.review_service import (
    assign_log_to_command,
    ignore_review_log,
    list_review_logs,
)


def _make_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def test_assign_log_to_command_creates_review_example_and_marks_dirty() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
        )
        log = NormalizationLog(
            raw_text="start broadcasting",
            normalized_text="start broadcasting",
            review_status=ReviewStatus.PENDING,
        )
        session.add(command)
        session.add(log)
        session.commit()
        session.refresh(command)
        session.refresh(log)

        result = assign_log_to_command(
            session,
            log_id=log.id,
            command_id=command.id,
            match_type="semantic",
            language="en",
        )
        assert result is True

        example = session.exec(select(CommandExample)).first()
        assert example is not None
        assert example.phrase == "start broadcasting"
        assert example.normalized_phrase == "start broadcasting"
        assert example.match_type == MatchType.SEMANTIC
        assert example.source == ExampleSource.REVIEW

        updated_log = session.get(NormalizationLog, log.id)
        assert updated_log.review_status == ReviewStatus.CONVERTED_TO_EXAMPLE

        dirty = session.exec(select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")).first()
        assert dirty is not None
        assert dirty.value == "true"


def test_assign_log_to_command_avoids_duplicate_example() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        command = CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
        )
        log = NormalizationLog(
            raw_text="start broadcasting",
            normalized_text="start broadcasting",
            review_status=ReviewStatus.PENDING,
        )
        session.add(command)
        session.add(log)
        session.commit()
        session.refresh(command)
        session.refresh(log)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="another phrase",
                normalized_phrase="start broadcasting",
                match_type=MatchType.SEMANTIC,
                source=ExampleSource.ADMIN,
            )
        )
        session.commit()

        result = assign_log_to_command(
            session,
            log_id=log.id,
            command_id=command.id,
            match_type="semantic",
            language="en",
        )
        assert result is True
        examples = session.exec(select(CommandExample)).all()
        assert len(examples) == 1
        assert session.get(NormalizationLog, log.id).review_status == ReviewStatus.CONVERTED_TO_EXAMPLE


def test_ignore_review_log_marks_ignored() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        log = NormalizationLog(
            raw_text="weird phrase",
            normalized_text="weird phrase",
            review_status=ReviewStatus.PENDING,
        )
        session.add(log)
        session.commit()
        session.refresh(log)

        result = ignore_review_log(session, log_id=log.id)
        assert result is True
        assert session.get(NormalizationLog, log.id).review_status == ReviewStatus.IGNORED


def test_list_review_logs_pending_filter() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        pending = NormalizationLog(
            raw_text="pending phrase",
            normalized_text="pending phrase",
            review_status=ReviewStatus.PENDING,
        )
        ignored = NormalizationLog(
            raw_text="ignored phrase",
            normalized_text="ignored phrase",
            review_status=ReviewStatus.IGNORED,
        )
        session.add(pending)
        session.add(ignored)
        session.commit()

        rows = list_review_logs(session, review_filter="pending")

        assert [row["log"].raw_text for row in rows] == ["pending phrase"]


def test_list_review_logs_unknown_needs_confirmation_and_audio_filters() -> None:
    engine = _make_engine()
    with Session(engine) as session:
        unknown = NormalizationLog(
            raw_text="unknown phrase",
            normalized_text="unknown phrase",
            result_json={"commands": [{"command": "UNKNOWN"}]},
            needs_confirmation=True,
            review_status=ReviewStatus.PENDING,
        )
        audio = NormalizationLog(
            raw_text="audio phrase",
            normalized_text="audio phrase",
            result_json={"commands": [{"command": "MOVE_LEFT"}]},
            needs_confirmation=False,
            review_status=ReviewStatus.PENDING,
        )
        session.add(unknown)
        session.add(audio)
        session.add(
            AudioTranscriptionLog(
                transcribed_text="audio phrase",
                engine="faster_whisper",
                model="base",
                used_for_normalization=True,
            )
        )
        session.commit()

        unknown_rows = list_review_logs(session, review_filter="unknown")
        needs_confirmation_rows = list_review_logs(
            session,
            review_filter="needs_confirmation",
        )
        audio_rows = list_review_logs(session, review_filter="audio_only")

        assert [row["log"].raw_text for row in unknown_rows] == ["unknown phrase"]
        assert [row["log"].raw_text for row in needs_confirmation_rows] == [
            "unknown phrase"
        ]
        assert [row["log"].raw_text for row in audio_rows] == ["audio phrase"]
        assert audio_rows[0]["is_audio"] is True
