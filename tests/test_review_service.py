from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AppSetting,
    CommandDefinition,
    CommandExample,
    CommandName,
    ExampleSource,
    MatchType,
    NormalizationLog,
    ReviewStatus,
)
from app.services.review_service import assign_log_to_command, ignore_review_log


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
