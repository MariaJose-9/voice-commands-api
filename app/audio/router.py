"""Public API routes for audio transcription and normalization."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Form, HTTPException, UploadFile

from app.audio.schemas import (
    AudioNormalizeResponse,
    AudioStatusResponse,
    AudioTranscriptionResponse,
    AudioWarmupResponse,
)
from app.audio.log_service import save_audio_transcription_log
from app.audio.temp_files import cleanup_temp_file, save_upload_file_to_temp
from app.audio.transcription_service import (
    get_effective_transcription_settings,
    is_transcription_model_loaded,
    transcribe_audio_file,
    warmup_transcription_model,
)
from app.config import (
    ENABLE_AUDIO_TRANSCRIPTION,
    ENABLE_SEMANTIC_MATCHER,
    TRANSCRIPTION_ENGINE,
    TRANSCRIPTION_MODEL_NAME,
)
from app.db.models import CatalogStatus, CatalogVersion
from app.db.session import Session as SessionFactory, engine
from app.normalizer import normalize_command_text
from app.services.normalization_log_service import save_normalization_log
from app.services.runtime_settings_service import get_bool_setting
from app.services.settings_service import is_catalog_dirty

try:
    from sqlmodel import select
except ImportError:  # pragma: no cover
    select = None


logger = logging.getLogger(__name__)

router = APIRouter(tags=["audio"])


def _catalog_runtime_status() -> tuple[Optional[int], bool]:
    """Return active catalog version and dirty flag without making audio status fragile."""

    if SessionFactory is None or engine is None or select is None:
        return None, False

    try:
        with SessionFactory(engine) as session:
            active_version = session.exec(
                select(CatalogVersion)
                .where(CatalogVersion.status == CatalogStatus.ACTIVE)
                .order_by(CatalogVersion.version_number.desc())
            ).first()
            return (
                active_version.version_number if active_version is not None else None,
                is_catalog_dirty(session),
            )
    except Exception:
        logger.warning(
            "Audio status could not read catalog runtime status",
            extra={"event": "audio_status_catalog_warning"},
            exc_info=True,
        )
        return None, False


def _audio_status_payload() -> AudioStatusResponse:
    settings = get_effective_transcription_settings()
    active_version, catalog_dirty = _catalog_runtime_status()
    return AudioStatusResponse(
        enabled=bool(settings["enabled"]),
        engine=str(settings["engine"]),
        model=str(settings["model_name"]),
        device=str(settings["device"]),
        compute_type=str(settings["compute_type"]),
        model_loaded=is_transcription_model_loaded(),
        allowed_extensions=list(settings["allowed_extensions"]),
        max_file_mb=int(settings["max_file_mb"]),
        max_duration_seconds=int(settings["max_duration_seconds"]),
        semantic_matcher_enabled=get_bool_setting(
            "ENABLE_SEMANTIC_MATCHER",
            ENABLE_SEMANTIC_MATCHER,
        ),
        active_catalog_version=active_version,
        catalog_dirty=catalog_dirty,
    )


def _raise_audio_http_error(exc: Exception) -> None:
    message = str(exc)
    lowered = message.lower()

    if "disabled" in lowered:
        raise HTTPException(status_code=503, detail=message) from exc
    if "maximum size" in lowered or "duration exceeds maximum" in lowered:
        raise HTTPException(status_code=413, detail=message) from exc
    if isinstance(exc, ValueError):
        raise HTTPException(status_code=400, detail=message) from exc
    if isinstance(exc, RuntimeError):
        raise HTTPException(status_code=500, detail=message) from exc
    raise HTTPException(status_code=500, detail="Internal audio processing error.") from exc


def _parse_context_json(context_json: Optional[str]) -> Optional[dict[str, Any]]:
    if context_json is None or not context_json.strip():
        return None
    try:
        parsed = json.loads(context_json)
    except json.JSONDecodeError as exc:
        raise ValueError("context_json must be valid JSON.") from exc
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise ValueError("context_json must decode to an object.")
    return parsed


def process_audio_transcription_upload(
    file: UploadFile,
    language_hint: Optional[str] = None,
) -> AudioTranscriptionResponse:
    """Shared transcription flow for API and admin routes."""

    temp_path: Optional[Path] = None
    size_bytes: Optional[int] = None
    settings = get_effective_transcription_settings()

    try:
        temp_path, size_bytes = save_upload_file_to_temp(file)
        response = transcribe_audio_file(temp_path, language_hint=language_hint)
        try:
            save_audio_transcription_log(
                filename=file.filename,
                content_type=file.content_type,
                size_bytes=size_bytes,
                language_hint=language_hint,
                detected_language=response.language,
                transcribed_text=response.text,
                duration_seconds=response.duration_seconds,
                engine_name=response.engine,
                model_name=response.model,
                ok=True,
                error_message=None,
                used_for_normalization=False,
            )
        except Exception:
            logger.warning(
                "Audio transcription success log raised unexpectedly",
                extra={"event": "audio_transcription_log_warning"},
                exc_info=True,
            )
        return response
    except Exception as exc:
        try:
            save_audio_transcription_log(
                filename=file.filename,
                content_type=file.content_type,
                size_bytes=size_bytes,
                language_hint=language_hint,
                detected_language=None,
                transcribed_text=None,
                duration_seconds=None,
                engine_name=str(settings["engine"]),
                model_name=str(settings["model_name"]),
                ok=False,
                error_message=str(exc),
                used_for_normalization=False,
            )
        except Exception:
            logger.warning(
                "Audio transcription failure log raised unexpectedly",
                extra={"event": "audio_transcription_log_warning"},
                exc_info=True,
            )
        raise
    finally:
        if temp_path is not None:
            cleanup_temp_file(temp_path)


def process_audio_normalization_upload(
    file: UploadFile,
    language_hint: Optional[str] = None,
    context_json: Optional[str] = None,
) -> AudioNormalizeResponse:
    """Shared transcribe+normalize flow for API and admin routes."""

    temp_path: Optional[Path] = None
    size_bytes: Optional[int] = None
    settings = get_effective_transcription_settings()

    try:
        temp_path, size_bytes = save_upload_file_to_temp(file)
        transcription = transcribe_audio_file(temp_path, language_hint=language_hint)
        context = _parse_context_json(context_json)
        normalization = normalize_command_text(
            text=transcription.text,
            language_hint=language_hint or transcription.language,
            context=context,
        )
        try:
            save_normalization_log(
                raw_text=transcription.text,
                normalized_text=normalization.normalized_text,
                language=normalization.language,
                response=normalization,
            )
        except Exception:
            logger.warning(
                "Audio normalization log persistence raised unexpectedly",
                extra={"event": "normalization_log_warning"},
                exc_info=True,
            )
        try:
            save_audio_transcription_log(
                filename=file.filename,
                content_type=file.content_type,
                size_bytes=size_bytes,
                language_hint=language_hint,
                detected_language=transcription.language,
                transcribed_text=transcription.text,
                duration_seconds=transcription.duration_seconds,
                engine_name=transcription.engine,
                model_name=transcription.model,
                ok=True,
                error_message=None,
                used_for_normalization=True,
            )
        except Exception:
            logger.warning(
                "Audio normalization transcription log raised unexpectedly",
                extra={"event": "audio_transcription_log_warning"},
                exc_info=True,
            )

        return AudioNormalizeResponse(
            ok=transcription.ok and normalization.ok,
            transcription=transcription,
            normalization=normalization,
            message=None,
        )
    except Exception as exc:
        try:
            save_audio_transcription_log(
                filename=file.filename,
                content_type=file.content_type,
                size_bytes=size_bytes,
                language_hint=language_hint,
                detected_language=None,
                transcribed_text=None,
                duration_seconds=None,
                engine_name=str(settings["engine"]),
                model_name=str(settings["model_name"]),
                ok=False,
                error_message=str(exc),
                used_for_normalization=True,
            )
        except Exception:
            logger.warning(
                "Audio normalization failure log raised unexpectedly",
                extra={"event": "audio_transcription_log_warning"},
                exc_info=True,
            )
        raise
    finally:
        if temp_path is not None:
            cleanup_temp_file(temp_path)


@router.get(
    "/v1/audio/status",
    response_model=AudioStatusResponse,
    summary="Get audio transcription status",
    description=(
        "Returns the current runtime status for the local audio transcription "
        "subsystem, including engine, model, device, allowed extensions, and "
        "whether the transcription model is already loaded in memory."
    ),
)
def read_audio_status() -> AudioStatusResponse:
    return _audio_status_payload()


@router.post(
    "/v1/audio/warmup",
    response_model=AudioWarmupResponse,
    summary="Warm up the audio transcription model",
    description=(
        "Loads the configured local transcription model into memory without "
        "performing a real transcription. Useful to reduce latency on the first "
        "real audio request."
    ),
)
def warmup_audio() -> AudioWarmupResponse:
    settings = get_effective_transcription_settings()
    if not settings["enabled"]:
        return AudioWarmupResponse(
            enabled=False,
            loaded=False,
            engine=str(settings["engine"]),
            model=str(settings["model_name"]),
            message="Audio transcription is disabled.",
        )

    try:
        return warmup_transcription_model()
    except Exception as exc:
        logger.exception(
            "Failed to warm up audio transcription model",
            extra={"event": "audio_warmup_error"},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error while warming up audio transcription.",
        ) from exc


@router.post(
    "/v1/audio/transcribe",
    response_model=AudioTranscriptionResponse,
    summary="Transcribe an audio file",
    description=(
        "Accepts `multipart/form-data` with an uploaded audio file and an optional "
        "`language_hint`. Supports `.ogg`, `.mp3`, and `.m4a` uploads. Returns the raw "
        "transcribed text and segment timing metadata. This endpoint only "
        "transcribes audio and does not normalize commands.\n\n"
        "Example form fields:\n"
        "- `file`: `command.m4a`\n"
        "- `language_hint`: `es`"
    ),
)
def transcribe_audio(
    file: UploadFile,
    language_hint: Optional[str] = Form(
        default=None,
        description="Optional language hint such as `en` or `es`.",
    ),
) -> AudioTranscriptionResponse:
    logger.info(
        "audio transcription request received",
        extra={"event": "audio_transcribe_request"},
    )

    try:
        response = process_audio_transcription_upload(file, language_hint=language_hint)
        logger.info(
            "audio transcription request completed",
            extra={"event": "audio_transcribe_success"},
        )
        return response
    except Exception as exc:
        logger.exception(
            "audio transcription request failed",
            extra={"event": "audio_transcribe_error"},
        )
        _raise_audio_http_error(exc)


@router.post(
    "/v1/audio/normalize",
    response_model=AudioNormalizeResponse,
    summary="Transcribe audio and normalize commands",
    description=(
        "Accepts `multipart/form-data`, transcribes the uploaded audio locally, "
        "and then runs the existing command normalizer over the transcribed text. "
        "Returns both the transcription payload and the normalization result. "
        "Supports `.ogg`, `.mp3`, and `.m4a` uploads.\n\n"
        "Example form fields:\n"
        "- `file`: `command.m4a`\n"
        "- `language_hint`: `en`\n"
        '- `context_json`: `{\"selected_monitor\": null, \"active_action\": \"stream\"}`'
    ),
)
def normalize_audio(
    file: UploadFile,
    language_hint: Optional[str] = Form(
        default=None,
        description="Optional language hint such as `en` or `es`.",
    ),
    context_json: Optional[str] = Form(
        default=None,
        description="Optional JSON object encoded as string for normalizer context.",
    ),
) -> AudioNormalizeResponse:
    logger.info(
        "audio normalization request received",
        extra={"event": "audio_normalize_request"},
    )

    try:
        response = process_audio_normalization_upload(
            file,
            language_hint=language_hint,
            context_json=context_json,
        )
        logger.info(
            "audio normalization request completed",
            extra={"event": "audio_normalize_success"},
        )
        return response
    except Exception as exc:
        logger.exception(
            "audio normalization request failed",
            extra={"event": "audio_normalize_error"},
        )
        _raise_audio_http_error(exc)
