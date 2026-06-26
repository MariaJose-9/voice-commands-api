"""Temporary file handling for uploaded audio."""

from __future__ import annotations

import logging
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile

from app.config import AUDIO_TEMP_DIR
from app.audio.validators import (
    sanitize_audio_filename,
    validate_audio_content_type,
    validate_audio_filename,
    validate_audio_size,
)


logger = logging.getLogger(__name__)

_CHUNK_SIZE = 1024 * 1024


def ensure_audio_temp_dir() -> Path:
    """Ensure the configured temporary audio directory exists."""

    temp_dir = Path(AUDIO_TEMP_DIR)
    temp_dir.mkdir(parents=True, exist_ok=True)
    return temp_dir


def save_upload_file_to_temp(upload_file: UploadFile) -> tuple[Path, int]:
    """Persist an uploaded audio file to a temporary location.

    The file is validated by extension, content type, and cumulative size
    while being copied in chunks to avoid loading it entirely into memory.
    """

    extension = validate_audio_filename(upload_file.filename or "")
    validate_audio_content_type(upload_file.content_type, extension)

    temp_dir = ensure_audio_temp_dir()
    sanitized_name = sanitize_audio_filename(upload_file.filename or f"audio{extension}")
    target_name = f"{Path(sanitized_name).stem}_{uuid4().hex}{extension}"
    target_path = temp_dir / target_name

    size_bytes = 0
    try:
        upload_file.file.seek(0)
        with target_path.open("wb") as temp_file:
            while True:
                chunk = upload_file.file.read(_CHUNK_SIZE)
                if not chunk:
                    break
                temp_file.write(chunk)
                size_bytes += len(chunk)
                validate_audio_size(size_bytes)
    except Exception:
        cleanup_temp_file(target_path)
        raise

    return target_path, size_bytes


def cleanup_temp_file(path: Path) -> None:
    """Remove a temporary audio file if it exists."""

    try:
        path.unlink(missing_ok=True)
    except Exception:
        logger.warning(
            "Failed to remove temporary audio file",
            extra={"event": "audio_temp_cleanup_warning"},
            exc_info=True,
        )
