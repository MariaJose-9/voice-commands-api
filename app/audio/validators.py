"""Validation helpers for uploaded audio files."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from app.config import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_AUDIO_MIME_TYPES,
    MAX_AUDIO_FILE_MB,
)


def is_allowed_audio_extension(extension: str) -> bool:
    """Return True when the normalized extension is allowed."""

    return extension.lower() in {item.lower() for item in ALLOWED_AUDIO_EXTENSIONS}


def validate_audio_filename(filename: str) -> str:
    """Validate a filename and return its normalized extension."""

    if not filename or not filename.strip():
        raise ValueError("Audio filename is required.")

    extension = Path(filename).suffix.lower()
    if not extension:
        raise ValueError("Audio filename must include a valid extension.")
    if not is_allowed_audio_extension(extension):
        raise ValueError(
            f"Unsupported audio file extension: {extension}. "
            f"Allowed extensions: {', '.join(ALLOWED_AUDIO_EXTENSIONS)}."
        )
    return extension


def validate_audio_content_type(content_type: Optional[str], extension: str) -> None:
    """Validate the declared content type against configured audio MIME types."""

    if not is_allowed_audio_extension(extension):
        raise ValueError("Audio extension is not allowed.")

    normalized_content_type = (content_type or "").strip().lower()
    allowed_types = {item.lower() for item in ALLOWED_AUDIO_MIME_TYPES}

    if not normalized_content_type:
        raise ValueError("Audio content type is required.")
    if normalized_content_type == "application/octet-stream":
        return
    if normalized_content_type not in allowed_types:
        raise ValueError(
            f"Unsupported audio content type: {normalized_content_type}. "
            f"Allowed MIME types: {', '.join(ALLOWED_AUDIO_MIME_TYPES)}."
        )


def validate_audio_size(size_bytes: int) -> None:
    """Validate uploaded audio size using configured megabyte limit."""

    max_size_bytes = MAX_AUDIO_FILE_MB * 1024 * 1024
    if size_bytes < 0:
        raise ValueError("Audio size must be zero or positive.")
    if size_bytes > max_size_bytes:
        raise ValueError(
            f"Audio file exceeds maximum size of {MAX_AUDIO_FILE_MB} MB."
        )


def sanitize_audio_filename(filename: str) -> str:
    """Strip path components and unsafe characters from an audio filename."""

    base_name = Path(filename or "").name
    if not base_name:
        return "audio"

    extension = Path(base_name).suffix.lower()
    stem = Path(base_name).stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    safe_stem = safe_stem or "audio"

    if extension and is_allowed_audio_extension(extension):
        return f"{safe_stem}{extension}"
    return safe_stem
