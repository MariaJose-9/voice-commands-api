from __future__ import annotations

import importlib


def _reload_config(monkeypatch):
    keys = [
        "ENABLE_AUDIO_TRANSCRIPTION",
        "TRANSCRIPTION_ENGINE",
        "TRANSCRIPTION_MODEL_NAME",
        "TRANSCRIPTION_DEVICE",
        "TRANSCRIPTION_COMPUTE_TYPE",
        "TRANSCRIPTION_BEAM_SIZE",
        "TRANSCRIPTION_VAD_FILTER",
        "TRANSCRIPTION_LANGUAGE_DEFAULT",
        "MAX_AUDIO_FILE_MB",
        "MAX_AUDIO_DURATION_SECONDS",
        "ALLOWED_AUDIO_EXTENSIONS",
        "ALLOWED_AUDIO_MIME_TYPES",
        "AUDIO_TEMP_DIR",
        "AUDIO_MODEL_WARMUP_ON_STARTUP",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)

    import app.config as config_module

    return importlib.reload(config_module)


def test_audio_config_defaults(monkeypatch) -> None:
    config_module = _reload_config(monkeypatch)

    assert config_module.ENABLE_AUDIO_TRANSCRIPTION is True
    assert config_module.TRANSCRIPTION_ENGINE == "faster_whisper"
    assert config_module.TRANSCRIPTION_MODEL_NAME == "base"
    assert config_module.TRANSCRIPTION_DEVICE == "cpu"
    assert config_module.TRANSCRIPTION_COMPUTE_TYPE == "int8"
    assert config_module.TRANSCRIPTION_BEAM_SIZE == 1
    assert config_module.TRANSCRIPTION_VAD_FILTER is False
    assert config_module.TRANSCRIPTION_LANGUAGE_DEFAULT == ""
    assert config_module.MAX_AUDIO_FILE_MB == 10
    assert config_module.MAX_AUDIO_DURATION_SECONDS == 30
    assert config_module.ALLOWED_AUDIO_EXTENSIONS == [".ogg", ".mp3"]
    assert config_module.ALLOWED_AUDIO_MIME_TYPES == [
        "audio/ogg",
        "audio/mpeg",
        "audio/mp3",
        "application/octet-stream",
    ]
    assert config_module.AUDIO_TEMP_DIR == "/tmp/voice-command-audio"
    assert config_module.AUDIO_MODEL_WARMUP_ON_STARTUP is False


def test_audio_config_reads_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("ENABLE_AUDIO_TRANSCRIPTION", "false")
    monkeypatch.setenv("TRANSCRIPTION_ENGINE", "custom_engine")
    monkeypatch.setenv("TRANSCRIPTION_MODEL_NAME", "small")
    monkeypatch.setenv("TRANSCRIPTION_DEVICE", "cuda")
    monkeypatch.setenv("TRANSCRIPTION_COMPUTE_TYPE", "float16")
    monkeypatch.setenv("TRANSCRIPTION_BEAM_SIZE", "3")
    monkeypatch.setenv("TRANSCRIPTION_VAD_FILTER", "true")
    monkeypatch.setenv("TRANSCRIPTION_LANGUAGE_DEFAULT", "es")
    monkeypatch.setenv("MAX_AUDIO_FILE_MB", "25")
    monkeypatch.setenv("MAX_AUDIO_DURATION_SECONDS", "90")
    monkeypatch.setenv("ALLOWED_AUDIO_EXTENSIONS", ".ogg,.mp3,.wav")
    monkeypatch.setenv(
        "ALLOWED_AUDIO_MIME_TYPES",
        "audio/ogg,audio/mpeg,audio/wav",
    )
    monkeypatch.setenv("AUDIO_TEMP_DIR", "/var/tmp/audio")
    monkeypatch.setenv("AUDIO_MODEL_WARMUP_ON_STARTUP", "true")

    import app.config as config_module

    config_module = importlib.reload(config_module)

    assert config_module.ENABLE_AUDIO_TRANSCRIPTION is False
    assert config_module.TRANSCRIPTION_ENGINE == "custom_engine"
    assert config_module.TRANSCRIPTION_MODEL_NAME == "small"
    assert config_module.TRANSCRIPTION_DEVICE == "cuda"
    assert config_module.TRANSCRIPTION_COMPUTE_TYPE == "float16"
    assert config_module.TRANSCRIPTION_BEAM_SIZE == 3
    assert config_module.TRANSCRIPTION_VAD_FILTER is True
    assert config_module.TRANSCRIPTION_LANGUAGE_DEFAULT == "es"
    assert config_module.MAX_AUDIO_FILE_MB == 25
    assert config_module.MAX_AUDIO_DURATION_SECONDS == 90
    assert config_module.ALLOWED_AUDIO_EXTENSIONS == [".ogg", ".mp3", ".wav"]
    assert config_module.ALLOWED_AUDIO_MIME_TYPES == [
        "audio/ogg",
        "audio/mpeg",
        "audio/wav",
    ]
    assert config_module.AUDIO_TEMP_DIR == "/var/tmp/audio"
    assert config_module.AUDIO_MODEL_WARMUP_ON_STARTUP is True
