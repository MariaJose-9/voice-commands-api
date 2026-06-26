from __future__ import annotations

import pytest

from app.audio.validators import (
    is_allowed_audio_extension,
    sanitize_audio_filename,
    validate_audio_content_type,
    validate_audio_filename,
    validate_audio_size,
)


def test_validate_audio_filename_accepts_ogg() -> None:
    assert validate_audio_filename("file.ogg") == ".ogg"


def test_validate_audio_filename_accepts_mp3() -> None:
    assert validate_audio_filename("file.mp3") == ".mp3"


def test_validate_audio_filename_rejects_wav() -> None:
    with pytest.raises(ValueError, match="Unsupported audio file extension"):
        validate_audio_filename("file.wav")


def test_validate_audio_filename_rejects_exe() -> None:
    with pytest.raises(ValueError, match="Unsupported audio file extension"):
        validate_audio_filename("file.exe")


def test_validate_audio_content_type_accepts_audio_mpeg() -> None:
    validate_audio_content_type("audio/mpeg", ".mp3")


def test_validate_audio_content_type_accepts_audio_ogg() -> None:
    validate_audio_content_type("audio/ogg", ".ogg")


def test_validate_audio_content_type_accepts_octet_stream_for_valid_extension() -> None:
    validate_audio_content_type("application/octet-stream", ".mp3")


def test_validate_audio_content_type_rejects_invalid_content_type() -> None:
    with pytest.raises(ValueError, match="Unsupported audio content type"):
        validate_audio_content_type("image/png", ".mp3")


def test_validate_audio_size_rejects_too_large_file() -> None:
    with pytest.raises(ValueError, match="exceeds maximum size"):
        validate_audio_size((10 * 1024 * 1024) + 1)


def test_sanitize_audio_filename_removes_path_traversal() -> None:
    assert sanitize_audio_filename("../../audio.mp3") == "audio.mp3"


def test_is_allowed_audio_extension() -> None:
    assert is_allowed_audio_extension(".ogg") is True
    assert is_allowed_audio_extension(".mp3") is True
    assert is_allowed_audio_extension(".wav") is False
