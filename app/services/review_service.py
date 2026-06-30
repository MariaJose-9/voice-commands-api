"""Review workflow helpers for pending normalization logs."""

from __future__ import annotations

from datetime import timedelta

from sqlmodel import select

from app.db.models import (
    AudioTranscriptionLog,
    CommandDefinition,
    CommandExample,
    ExampleSource,
    MatchType,
    NormalizationLog,
    ReviewStatus,
    utc_now,
)
from app.preprocessor import normalize_text
from app.services.settings_service import set_catalog_dirty


def _log_has_unknown_command(log_row: NormalizationLog) -> bool:
    result_json = log_row.result_json or {}
    commands = result_json.get("commands", []) if isinstance(result_json, dict) else []
    return any(command.get("command") == "UNKNOWN" for command in commands)


def _audio_source_texts(session) -> set[str]:
    rows = session.exec(
        select(AudioTranscriptionLog).where(
            AudioTranscriptionLog.used_for_normalization.is_(True)
        )
    ).all()
    return {
        row.transcribed_text
        for row in rows
        if row.transcribed_text is not None and row.transcribed_text.strip()
    }


def list_review_logs(session, *, review_filter: str = "pending") -> list[dict]:
    """Return review log rows with UI metadata and supported filters."""

    filter_name = (review_filter or "pending").strip().lower()
    statement = select(NormalizationLog).where(
        NormalizationLog.review_status == ReviewStatus.PENDING
    )

    if filter_name == "needs_confirmation":
        statement = statement.where(NormalizationLog.needs_confirmation.is_(True))
    elif filter_name == "last_24h":
        statement = statement.where(
            NormalizationLog.created_at >= utc_now() - timedelta(hours=24)
        )
    elif filter_name == "last_7d":
        statement = statement.where(
            NormalizationLog.created_at >= utc_now() - timedelta(days=7)
        )

    logs = session.exec(statement.order_by(NormalizationLog.created_at.desc())).all()
    audio_texts = _audio_source_texts(session)
    rows = [
        {
            "log": log,
            "is_audio": bool(log.raw_text in audio_texts),
            "has_unknown": _log_has_unknown_command(log),
        }
        for log in logs
    ]

    if filter_name == "unknown":
        return [row for row in rows if row["has_unknown"]]
    if filter_name == "audio_only":
        return [row for row in rows if row["is_audio"]]
    return rows


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


def ignore_review_logs(session, *, log_ids: list[int]) -> int:
    """Mark multiple review logs as ignored."""

    updated = 0
    for log_id in log_ids:
        log_row = session.get(NormalizationLog, log_id)
        if log_row is None:
            continue
        log_row.review_status = ReviewStatus.IGNORED
        session.add(log_row)
        updated += 1
    session.commit()
    return updated


def assign_logs_to_command(
    session,
    *,
    log_ids: list[int],
    command_id: int,
    match_type: str,
    language: str | None = None,
) -> int:
    """Convert multiple logs into examples for the same command."""

    updated = 0
    for log_id in log_ids:
        if assign_log_to_command(
            session,
            log_id=log_id,
            command_id=command_id,
            match_type=match_type,
            language=language,
        ):
            updated += 1
    return updated
