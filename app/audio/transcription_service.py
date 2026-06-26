"""Audio transcription service with pluggable providers."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import app.services.runtime_settings_service as runtime_settings_service
from app.audio.providers.base import TranscriptionProvider
from app.audio.providers.faster_whisper_provider import FasterWhisperProvider
from app.audio.schemas import AudioTranscriptionResponse, AudioWarmupResponse
from app.config import (
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_AUDIO_MIME_TYPES,
    AUDIO_MODEL_WARMUP_ON_STARTUP,
    AUDIO_TEMP_DIR,
    ENABLE_AUDIO_TRANSCRIPTION,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_FILE_MB,
    TRANSCRIPTION_BEAM_SIZE,
    TRANSCRIPTION_COMPUTE_TYPE,
    TRANSCRIPTION_DEVICE,
    TRANSCRIPTION_ENGINE,
    TRANSCRIPTION_LANGUAGE_DEFAULT,
    TRANSCRIPTION_MODEL_NAME,
    TRANSCRIPTION_VAD_FILTER,
)


_provider: TranscriptionProvider | None = None
_provider_signature: tuple[str, str, str, str] | None = None


def get_effective_transcription_settings() -> dict[str, object]:
    """Return runtime-effective transcription settings with DB fallback."""

    return {
        "enabled": runtime_settings_service.get_audio_bool_setting(
            "ENABLE_AUDIO_TRANSCRIPTION",
            ENABLE_AUDIO_TRANSCRIPTION,
        ),
        "engine": runtime_settings_service.get_audio_str_setting(
            "TRANSCRIPTION_ENGINE",
            TRANSCRIPTION_ENGINE,
        ),
        "model_name": runtime_settings_service.get_audio_str_setting(
            "TRANSCRIPTION_MODEL_NAME",
            TRANSCRIPTION_MODEL_NAME,
        ),
        "device": runtime_settings_service.get_audio_str_setting(
            "TRANSCRIPTION_DEVICE",
            TRANSCRIPTION_DEVICE,
        ),
        "compute_type": runtime_settings_service.get_audio_str_setting(
            "TRANSCRIPTION_COMPUTE_TYPE",
            TRANSCRIPTION_COMPUTE_TYPE,
        ),
        "beam_size": runtime_settings_service.get_audio_int_setting(
            "TRANSCRIPTION_BEAM_SIZE",
            TRANSCRIPTION_BEAM_SIZE,
        ),
        "vad_filter": runtime_settings_service.get_audio_bool_setting(
            "TRANSCRIPTION_VAD_FILTER",
            TRANSCRIPTION_VAD_FILTER,
        ),
        "language_default": runtime_settings_service.get_audio_str_setting(
            "TRANSCRIPTION_LANGUAGE_DEFAULT",
            TRANSCRIPTION_LANGUAGE_DEFAULT,
        ),
        "max_file_mb": runtime_settings_service.get_audio_int_setting(
            "MAX_AUDIO_FILE_MB",
            MAX_AUDIO_FILE_MB,
        ),
        "max_duration_seconds": runtime_settings_service.get_audio_int_setting(
            "MAX_AUDIO_DURATION_SECONDS",
            MAX_AUDIO_DURATION_SECONDS,
        ),
        "allowed_extensions": runtime_settings_service.get_audio_list_setting(
            "ALLOWED_AUDIO_EXTENSIONS",
            ALLOWED_AUDIO_EXTENSIONS,
        ),
        "allowed_mime_types": runtime_settings_service.get_audio_list_setting(
            "ALLOWED_AUDIO_MIME_TYPES",
            ALLOWED_AUDIO_MIME_TYPES,
        ),
        "audio_temp_dir": runtime_settings_service.get_audio_str_setting(
            "AUDIO_TEMP_DIR",
            AUDIO_TEMP_DIR,
        ),
        "warmup_on_startup": runtime_settings_service.get_audio_bool_setting(
            "AUDIO_MODEL_WARMUP_ON_STARTUP",
            AUDIO_MODEL_WARMUP_ON_STARTUP,
        ),
    }


def _provider_signature_from_settings(settings: dict[str, object]) -> tuple[str, str, str, str]:
    return (
        str(settings["engine"]),
        str(settings["model_name"]),
        str(settings["device"]),
        str(settings["compute_type"]),
    )


def _build_provider(settings: dict[str, object]) -> TranscriptionProvider:
    engine = str(settings["engine"])
    if engine == "faster_whisper":
        return FasterWhisperProvider(settings)
    raise RuntimeError(f"Unsupported transcription engine: {engine}.")


def get_transcription_provider(force_reload: bool = False) -> TranscriptionProvider:
    """Return the active provider based on runtime settings."""

    global _provider, _provider_signature

    settings = get_effective_transcription_settings()
    if not settings["enabled"]:
        raise RuntimeError("Audio transcription is disabled.")

    signature = _provider_signature_from_settings(settings)
    if _provider is not None and not force_reload and _provider_signature == signature:
        return _provider

    _provider = _build_provider(settings)
    _provider_signature = signature
    return _provider


def get_transcription_model(force_reload: bool = False):
    """Compatibility wrapper returning the underlying provider model/client."""

    provider = get_transcription_provider(force_reload=force_reload)
    return provider.load(force_reload=force_reload)


def is_transcription_model_loaded() -> bool:
    """Return whether the active provider is already loaded."""

    if _provider is None:
        return False
    return _provider.is_loaded()


def warmup_transcription_model(force_reload: bool = False) -> AudioWarmupResponse:
    """Load the configured provider without running a real transcription."""

    settings = get_effective_transcription_settings()
    provider = get_transcription_provider(force_reload=force_reload)
    provider.warmup(force_reload=force_reload)
    return AudioWarmupResponse(
        enabled=bool(settings["enabled"]),
        loaded=provider.is_loaded(),
        engine=str(settings["engine"]),
        model=str(settings["model_name"]),
        message=None,
    )


def transcribe_audio_file(
    file_path: Path,
    language_hint: Optional[str] = None,
) -> AudioTranscriptionResponse:
    """Transcribe an audio file using the configured provider."""

    provider = get_transcription_provider()
    return provider.transcribe(file_path, language_hint=language_hint)
