from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest
from starlette.datastructures import UploadFile

import app.audio.temp_files as temp_files
import app.audio.validators as validators


def _make_upload_file(
    filename: str,
    content: bytes,
    *,
    content_type: str = "audio/mpeg",
) -> UploadFile:
    return UploadFile(
        file=BytesIO(content),
        filename=filename,
        headers={"content-type": content_type},
    )


def test_save_upload_file_to_temp_and_cleanup(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(temp_files, "AUDIO_TEMP_DIR", str(tmp_path))
    upload_file = _make_upload_file("sample.mp3", b"fake-audio-data")

    path, size_bytes = temp_files.save_upload_file_to_temp(upload_file)

    assert path.exists()
    assert path.suffix == ".mp3"
    assert size_bytes == len(b"fake-audio-data")

    temp_files.cleanup_temp_file(path)
    assert not path.exists()


def test_save_upload_file_rejects_invalid_extension(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(temp_files, "AUDIO_TEMP_DIR", str(tmp_path))
    upload_file = _make_upload_file(
        "sample.exe",
        b"fake-audio-data",
        content_type="application/octet-stream",
    )

    with pytest.raises(ValueError, match="Unsupported audio file extension"):
        temp_files.save_upload_file_to_temp(upload_file)


def test_save_upload_file_rejects_too_large_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(temp_files, "AUDIO_TEMP_DIR", str(tmp_path))
    monkeypatch.setattr(validators, "MAX_AUDIO_FILE_MB", 1)
    upload_file = _make_upload_file("sample.mp3", b"x" * ((1024 * 1024) + 1))

    with pytest.raises(ValueError, match="exceeds maximum size"):
        temp_files.save_upload_file_to_temp(upload_file)

    assert list(Path(tmp_path).iterdir()) == []


def test_ensure_audio_temp_dir_creates_directory(tmp_path, monkeypatch) -> None:
    target_dir = tmp_path / "nested" / "audio"
    monkeypatch.setattr(temp_files, "AUDIO_TEMP_DIR", str(target_dir))

    resolved = temp_files.ensure_audio_temp_dir()

    assert resolved == target_dir
    assert target_dir.exists()
