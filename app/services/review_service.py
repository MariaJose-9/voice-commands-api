"""Review workflow helpers for pending normalization logs."""

from __future__ import annotations

from sqlmodel import select

from app.db.models import (
    CommandDefinition,
    CommandExample,
    ExampleSource,
    MatchType,
    NormalizationLog,
    ReviewStatus,
)
from app.preprocessor import normalize_text
from app.services.settings_service import set_catalog_dirty


def assign_log_to_command(
    session,
    *,
    log_id: int,
    command_id: int,
    match_type: str,
    language: str | None = None,
) -> bool:
    """Convert a pending review log into a command example."""

    log_row = session.get(NormalizationLog, log_id)
    command = session.get(CommandDefinition, command_id)
    if log_row is None or command is None:
        return False

    normalized_phrase = normalize_text(log_row.raw_text)
    duplicate = session.exec(
        select(CommandExample).where(
            CommandExample.command_id == command_id,
            CommandExample.normalized_phrase == normalized_phrase,
        )
    ).first()

    if duplicate is None:
        session.add(
            CommandExample(
                command_id=command_id,
                phrase=log_row.raw_text,
                normalized_phrase=normalized_phrase,
                language=(language.strip() or None) if language else None,
                match_type=MatchType(match_type),
                enabled=True,
                source=ExampleSource.REVIEW,
            )
        )

    log_row.review_status = ReviewStatus.CONVERTED_TO_EXAMPLE
    session.add(log_row)
    session.commit()
    set_catalog_dirty(session, True)
    return True


def ignore_review_log(session, *, log_id: int) -> bool:
    """Mark a pending review log as ignored."""

    log_row = session.get(NormalizationLog, log_id)
    if log_row is None:
        return False

    log_row.review_status = ReviewStatus.IGNORED
    session.add(log_row)
    session.commit()
    return True
