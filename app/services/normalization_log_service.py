"""Persistent normalization log helpers."""

from __future__ import annotations

import logging
from typing import Optional

from app.config import ENABLE_NORMALIZATION_LOGS
from app.db.models import NormalizationLog, ReviewStatus
from app.db.session import Session as SessionFactory, engine
from app.schemas import CommandName, NormalizeResponse
from app.services import runtime_settings_service
from app.services.completeness_checker import check_command_completeness


logger = logging.getLogger(__name__)


def _build_log_metadata(response: NormalizeResponse) -> dict:
    """Build audit metadata for normalization decisions."""

    message = response.message or ""
    llm_called = "LLM used" in message or "Completed with LLM" in message
    merged_with_llm = "Completed with LLM" in message
    if "LLM failed" in message:
        llm_called = True

    completeness = check_command_completeness(
        response.normalized_text,
        response.commands,
    )
    llm_reason = None
    if "LLM used:" in message:
        llm_reason = message.split("LLM used:", 1)[1].split(";", 1)[0].strip()
    elif "LLM failed" in message:
        llm_reason = "failed"

    return {
        "llm_mode": runtime_settings_service.get_runtime_str_setting(
            "LLM_COMMAND_MODE",
            "fallback",
        ),
        "llm_called": llm_called,
        "llm_reason": llm_reason,
        "llm_model": runtime_settings_service.get_runtime_str_setting(
            "OLLAMA_MODEL",
            "qwen2.5:3b",
        ),
        "completeness_reason": completeness.reason,
        "completeness_score": completeness.coverage_score,
        "merged_with_llm": merged_with_llm,
    }


def _response_json_with_metadata(response: NormalizeResponse) -> dict:
    result_json = response.model_dump(mode="json")
    result_json["metadata"] = _build_log_metadata(response)
    return result_json


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
                    result_json=_response_json_with_metadata(response),
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
