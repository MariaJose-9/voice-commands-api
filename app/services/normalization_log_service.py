"""Persistent normalization log helpers."""

from __future__ import annotations

import logging
from typing import Optional

from app.config import ENABLE_NORMALIZATION_LOGS
from app.db.models import NormalizationLog, ReviewStatus
from app.db.session import Session as SessionFactory, engine
from app.schemas import CommandName, NormalizeResponse


logger = logging.getLogger(__name__)


def save_normalization_log(
    raw_text: str,
    normalized_text: str,
    language: Optional[str],
    response: NormalizeResponse,
) -> None:
    """Persist a normalization result when logging is enabled.

    Failures are swallowed and logged as warnings to avoid impacting the API.
    """

    if not ENABLE_NORMALIZATION_LOGS:
        return
    if SessionFactory is None or engine is None:
        return

    top_confidence = max((command.confidence for command in response.commands), default=None)
    has_unknown = any(command.command == CommandName.UNKNOWN for command in response.commands)
    review_status = (
        ReviewStatus.PENDING
        if response.needs_confirmation or has_unknown
        else ReviewStatus.IGNORED
    )

    try:
        with SessionFactory(engine) as session:
            session.add(
                NormalizationLog(
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    language=language,
                    result_json=response.model_dump(mode="json"),
                    top_confidence=top_confidence,
                    needs_confirmation=response.needs_confirmation,
                    review_status=review_status,
                )
            )
            session.commit()
    except Exception:
        logger.warning(
            "Failed to persist normalization log",
            extra={"event": "normalization_log_warning"},
            exc_info=True,
        )
