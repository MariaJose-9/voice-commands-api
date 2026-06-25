"""Application configuration."""

from __future__ import annotations

import json
import logging
import os
from typing import Any


def _get_bool(name: str, default: bool) -> bool:
    """Read a boolean environment variable with a safe default."""

    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _get_float(name: str, default: float) -> float:
    """Read a float environment variable with a safe default."""

    value = os.getenv(name)
    if value is None:
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _get_int(name: str, default: int) -> int:
    """Read an integer environment variable with a safe default."""

    value = os.getenv(name)
    if value is None:
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _get_list(name: str, default: list[str]) -> list[str]:
    """Read a comma-separated environment variable into a list."""

    value = os.getenv(name)
    if value is None:
        return default
    parts = [item.strip() for item in value.split(",")]
    return [item for item in parts if item]


ENABLE_SEMANTIC_MATCHER = _get_bool("ENABLE_SEMANTIC_MATCHER", True)
ENABLE_OLLAMA_FALLBACK = _get_bool("ENABLE_OLLAMA_FALLBACK", False)
ENABLE_NORMALIZATION_LOGS = _get_bool("ENABLE_NORMALIZATION_LOGS", True)
ENV = os.getenv("ENV", "development")
ALLOWED_ORIGINS = _get_list(
    "ALLOWED_ORIGINS",
    ["*"] if ENV != "production" else [],
)
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "mysql+pymysql://voice_user:voice_password@localhost:3306/voice_command_api?charset=utf8mb4",
)
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "change-me-in-production")
ADMIN_COOKIE_NAME = os.getenv("ADMIN_COOKIE_NAME", "voice_admin_session")
ADMIN_SESSION_MAX_AGE_SECONDS = _get_int(
    "ADMIN_SESSION_MAX_AGE_SECONDS",
    86400,
)
ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "admin123")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
SEMANTIC_MODEL_NAME = os.getenv(
    "SEMANTIC_MODEL_NAME",
    "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
)
FUZZY_THRESHOLD = _get_float("FUZZY_THRESHOLD", 88.0)
SEMANTIC_THRESHOLD = _get_float("SEMANTIC_THRESHOLD", 0.72)
SEMANTIC_CONFIRMATION_THRESHOLD = _get_float(
    "SEMANTIC_CONFIRMATION_THRESHOLD",
    0.62,
)
MAX_TEXT_LENGTH = _get_int("MAX_TEXT_LENGTH", 500)
SEMANTIC_TIMEOUT_SECONDS = _get_float("SEMANTIC_TIMEOUT_SECONDS", 2.5)


class StructuredLogFormatter(logging.Formatter):
    """Minimal JSON formatter for production-oriented structured logs."""

    def format(self, record: Any) -> str:
        payload = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "event"):
            payload["event"] = record.event
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True)
