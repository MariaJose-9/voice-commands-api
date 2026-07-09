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


def test_validate_audio_filename_accepts_m4a() -> None:
    assert validate_audio_filename("file.m4a") == ".m4a"


def test_validate_audio_filename_accepts_mp4() -> None:
    assert validate_audio_filename("file.mp4") == ".mp4"


def test_validate_audio_filename_accepts_wav() -> None:
    assert validate_audio_filename("file.wav") == ".wav"


def test_validate_audio_filename_accepts_webm() -> None:
    assert validate_audio_filename("file.webm") == ".webm"


def test_validate_audio_filename_rejects_exe() -> None:
    with pytest.raises(ValueError, match="Unsupported audio file extension"):
        validate_audio_filename("file.exe")


def test_validate_audio_content_type_accepts_audio_mpeg() -> None:
    validate_audio_content_type("audio/mpeg", ".mp3")


def test_validate_audio_content_type_accepts_audio_ogg() -> None:
    validate_audio_content_type("audio/ogg", ".ogg")


def test_validate_audio_content_type_accepts_application_ogg() -> None:
    validate_audio_content_type("application/ogg", ".ogg")


def test_validate_audio_content_type_accepts_audio_mp4_for_m4a() -> None:
    validate_audio_content_type("audio/mp4", ".m4a")


def test_validate_audio_content_type_accepts_audio_x_m4a() -> None:
    validate_audio_content_type("audio/x-m4a", ".m4a")


def test_validate_audio_content_type_accepts_audio_m4a() -> None:
    validate_audio_content_type("audio/m4a", ".m4a")


def test_validate_audio_content_type_accepts_video_mp4_for_mp4() -> None:
    validate_audio_content_type("video/mp4", ".mp4")


def test_validate_audio_content_type_accepts_audio_wav() -> None:
    validate_audio_content_type("audio/wav", ".wav")


def test_validate_audio_content_type_accepts_audio_wave() -> None:
    validate_audio_content_type("audio/wave", ".wav")


def test_validate_audio_content_type_accepts_audio_vnd_wave() -> None:
    validate_audio_content_type("audio/vnd.wave", ".wav")


def test_validate_audio_content_type_accepts_audio_webm() -> None:
    validate_audio_content_type("audio/webm", ".webm")


def test_validate_audio_content_type_accepts_audio_x_aac() -> None:
    validate_audio_content_type("audio/x-aac", ".aac")


def test_validate_audio_content_type_accepts_audio_x_flac() -> None:
    validate_audio_content_type("audio/x-flac", ".flac")


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
    assert is_allowed_audio_extension(".m4a") is True
    assert is_allowed_audio_extension(".mp4") is True
    assert is_allowed_audio_extension(".wav") is True
    assert is_allowed_audio_extension(".webm") is True
    assert is_allowed_audio_extension(".aac") is True
    assert is_allowed_audio_extension(".flac") is True
    assert is_allowed_audio_extension(".exe") is False
