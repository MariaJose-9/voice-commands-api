"""Admin panel routes."""

from __future__ import annotations

from pathlib import Path
import json
import re
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlmodel import select
import yaml

from app.admin.auth import (
    ADMIN_COOKIE_NAME,
    authenticate_admin_user,
    create_session_token,
    decode_session_token,
    get_csrf_token,
    get_current_admin_user,
)
from app.admin.forms import (
    CommandCreateForm,
    CommandParameterCreateForm,
    CommandParameterUpdateForm,
    CommandUpdateForm,
    EntityAliasCreateForm,
    EntityAliasUpdateForm,
    EntityTypeCreateForm,
    EntityValueCreateForm,
    EntityValueUpdateForm,
    ExampleCreateForm,
    ExampleUpdateForm,
    LoginForm,
)
from app.audio.router import (
    process_audio_normalization_upload,
    process_audio_transcription_upload,
)
from app.config import (
    ADMIN_SESSION_MAX_AGE_SECONDS,
    ALLOWED_AUDIO_EXTENSIONS,
    ALLOWED_AUDIO_MIME_TYPES,
    ALLOWED_SIZE_INCHES,
    ALLOW_DYNAMIC_SIZE_INCHES,
    DEBUG_LLM_PROMPT,
    ENABLE_SEMANTIC_MATCHER,
    ENABLE_AUDIO_TRANSCRIPTION,
    ENV,
    ENABLE_OLLAMA_FALLBACK,
    FUZZY_THRESHOLD,
    LLM_ACCEPT_THRESHOLD,
    LLM_COMMAND_MODE,
    LLM_CONFIDENCE_CAP,
    LLM_USE_FULL_TEXT_ON_INCOMPLETE,
    LLM_USE_PREVIOUS_COMMANDS,
    MAX_TEXT_LENGTH,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_FILE_MB,
    MAX_SIZE_INCHES,
    MIN_SIZE_INCHES,
    OLLAMA_BASE_URL,
    OLLAMA_MODEL,
    OLLAMA_TIMEOUT_SECONDS,
    SEMANTIC_CONFIRMATION_THRESHOLD,
    SEMANTIC_MODEL_NAME,
    SEMANTIC_THRESHOLD,
    TRANSCRIPTION_BEAM_SIZE,
    TRANSCRIPTION_COMPUTE_TYPE,
    TRANSCRIPTION_DEVICE,
    TRANSCRIPTION_ENGINE,
    TRANSCRIPTION_LANGUAGE_DEFAULT,
    TRANSCRIPTION_MODEL_NAME,
    TRANSCRIPTION_VAD_FILTER,
)
from app.db.models import (
    AppSetting,
    AudioTranscriptionLog,
    AuditLog,
    CatalogStatus,
    CatalogVersion,
    CommandDefinition,
    CommandExample,
    CommandParameter,
    EntityType,
    EntityValue,
    EntityValueAlias,
    ExampleSource,
    MatchType,
    NormalizationLog,
    ReviewStatus,
    UserRole,
    utc_now,
)
from app.db.session import Session as SessionFactory, engine
from app.preprocessor import normalize_text
from app.services.catalog_service import export_catalog_to_yaml_shape
from app.schemas import CommandName, NormalizeRequest
from app.services.debug_service import build_debug_response
from app.services.publish_service import get_active_version, publish_catalog
from app.services.review_service import (
    assign_log_to_command,
    assign_logs_to_command,
    ignore_review_log,
    ignore_review_logs,
    list_review_logs,
)
from app.services.runtime_settings_service import (
    get_audio_list_setting,
    get_bool_setting,
    get_runtime_setting,
    get_str_setting,
)
from app.services.settings_service import is_catalog_dirty, set_catalog_dirty
from app.v2.normalizer import normalize_command_text_v2


router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
CUSTOM_COMMAND_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
CLIENT_ACTION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
SNAKE_CASE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
ENTITY_DATA_TYPES = {"string", "integer", "float", "enum", "boolean"}
MATCHING_SETTINGS = {
    "FUZZY_THRESHOLD",
    "SEMANTIC_THRESHOLD",
    "SEMANTIC_CONFIRMATION_THRESHOLD",
    "ENABLE_SEMANTIC_MATCHER",
    "SEMANTIC_MODEL_NAME",
    "ENABLE_OLLAMA_FALLBACK",
    "LLM_COMMAND_MODE",
    "OLLAMA_MODEL",
    "LLM_ACCEPT_THRESHOLD",
    "LLM_CONFIDENCE_CAP",
    "ALLOW_DYNAMIC_SIZE_INCHES",
    "MIN_SIZE_INCHES",
    "MAX_SIZE_INCHES",
    "ALLOWED_SIZE_INCHES",
}
LLM_SETTINGS_KEYS = {
    "ENABLE_OLLAMA_FALLBACK",
    "LLM_COMMAND_MODE",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "OLLAMA_TIMEOUT_SECONDS",
    "LLM_ACCEPT_THRESHOLD",
    "LLM_CONFIDENCE_CAP",
    "LLM_USE_FULL_TEXT_ON_INCOMPLETE",
    "LLM_USE_PREVIOUS_COMMANDS",
    "ALLOW_DYNAMIC_SIZE_INCHES",
    "MIN_SIZE_INCHES",
    "MAX_SIZE_INCHES",
    "ALLOWED_SIZE_INCHES",
    "DEBUG_LLM_PROMPT",
}
LLM_RUNTIME_REFRESH_SETTINGS = LLM_SETTINGS_KEYS
LLM_RESTART_REQUIRED_SETTINGS: set[str] = set()
EDITABLE_SETTINGS = {
    "FUZZY_THRESHOLD": FUZZY_THRESHOLD,
    "SEMANTIC_THRESHOLD": SEMANTIC_THRESHOLD,
    "SEMANTIC_CONFIRMATION_THRESHOLD": SEMANTIC_CONFIRMATION_THRESHOLD,
    "ENABLE_SEMANTIC_MATCHER": ENABLE_SEMANTIC_MATCHER,
    "ENABLE_OLLAMA_FALLBACK": ENABLE_OLLAMA_FALLBACK,
    "SEMANTIC_MODEL_NAME": SEMANTIC_MODEL_NAME,
    "MAX_TEXT_LENGTH": MAX_TEXT_LENGTH,
    "LLM_COMMAND_MODE": LLM_COMMAND_MODE,
    "OLLAMA_BASE_URL": OLLAMA_BASE_URL,
    "OLLAMA_MODEL": OLLAMA_MODEL,
    "OLLAMA_TIMEOUT_SECONDS": OLLAMA_TIMEOUT_SECONDS,
    "LLM_ACCEPT_THRESHOLD": LLM_ACCEPT_THRESHOLD,
    "LLM_CONFIDENCE_CAP": LLM_CONFIDENCE_CAP,
    "LLM_USE_FULL_TEXT_ON_INCOMPLETE": LLM_USE_FULL_TEXT_ON_INCOMPLETE,
    "LLM_USE_PREVIOUS_COMMANDS": LLM_USE_PREVIOUS_COMMANDS,
    "ALLOW_DYNAMIC_SIZE_INCHES": ALLOW_DYNAMIC_SIZE_INCHES,
    "MIN_SIZE_INCHES": MIN_SIZE_INCHES,
    "MAX_SIZE_INCHES": MAX_SIZE_INCHES,
    "ALLOWED_SIZE_INCHES": ALLOWED_SIZE_INCHES,
    "DEBUG_LLM_PROMPT": DEBUG_LLM_PROMPT,
    "ENABLE_AUDIO_TRANSCRIPTION": ENABLE_AUDIO_TRANSCRIPTION,
    "TRANSCRIPTION_ENGINE": TRANSCRIPTION_ENGINE,
    "TRANSCRIPTION_MODEL_NAME": TRANSCRIPTION_MODEL_NAME,
    "TRANSCRIPTION_DEVICE": TRANSCRIPTION_DEVICE,
    "TRANSCRIPTION_COMPUTE_TYPE": TRANSCRIPTION_COMPUTE_TYPE,
    "TRANSCRIPTION_BEAM_SIZE": TRANSCRIPTION_BEAM_SIZE,
    "TRANSCRIPTION_VAD_FILTER": TRANSCRIPTION_VAD_FILTER,
    "TRANSCRIPTION_LANGUAGE_DEFAULT": TRANSCRIPTION_LANGUAGE_DEFAULT,
    "MAX_AUDIO_FILE_MB": MAX_AUDIO_FILE_MB,
    "MAX_AUDIO_DURATION_SECONDS": MAX_AUDIO_DURATION_SECONDS,
    "ALLOWED_AUDIO_EXTENSIONS": ALLOWED_AUDIO_EXTENSIONS,
    "ALLOWED_AUDIO_MIME_TYPES": ALLOWED_AUDIO_MIME_TYPES,
}
AUDIO_SETTINGS_KEYS = {
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
}
AUDIO_MODEL_RELOAD_SETTINGS = {
    "TRANSCRIPTION_MODEL_NAME",
    "TRANSCRIPTION_DEVICE",
    "TRANSCRIPTION_COMPUTE_TYPE",
}
AUDIO_LIST_SETTINGS = {
    "ALLOWED_AUDIO_EXTENSIONS",
    "ALLOWED_AUDIO_MIME_TYPES",
}
LIST_SETTINGS = AUDIO_LIST_SETTINGS | {"ALLOWED_SIZE_INCHES"}
SETTING_DESCRIPTIONS = {
    "ENABLE_OLLAMA_FALLBACK": "Enable local Ollama command interpretation.",
    "LLM_COMMAND_MODE": "off, fallback, hybrid, or primary.",
    "OLLAMA_BASE_URL": "Base URL for local Ollama.",
    "OLLAMA_MODEL": "Ollama model name.",
    "OLLAMA_TIMEOUT_SECONDS": "LLM request timeout in seconds.",
    "LLM_ACCEPT_THRESHOLD": "Minimum confidence accepted without confirmation.",
    "LLM_CONFIDENCE_CAP": "Maximum confidence accepted from LLM.",
    "LLM_USE_FULL_TEXT_ON_INCOMPLETE": "Use full utterance when parser is incomplete.",
    "LLM_USE_PREVIOUS_COMMANDS": "Send parser results to LLM for completion.",
    "ALLOW_DYNAMIC_SIZE_INCHES": "Allow arbitrary sizes inside configured range.",
    "MIN_SIZE_INCHES": "Minimum dynamic size in inches.",
    "MAX_SIZE_INCHES": "Maximum dynamic size in inches.",
    "ALLOWED_SIZE_INCHES": "Comma-separated fixed sizes when dynamic sizes are off.",
    "DEBUG_LLM_PROMPT": "Show prompt in debug only in development.",
}
ROLE_ORDER = {
    UserRole.VIEWER: 0,
    UserRole.EDITOR: 1,
    UserRole.ADMIN: 2,
}
LOGIN_RATE_LIMIT_MAX_ATTEMPTS = 5
LOGIN_RATE_LIMIT_WINDOW_SECONDS = 900
LOGIN_RATE_LIMIT_BLOCK_SECONDS = 900
_LOGIN_FAILURES: dict[str, dict[str, float]] = {}


def _redirect_to_login() -> RedirectResponse:
    return RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)


def _forbidden_response() -> HTMLResponse:
    return HTMLResponse("Forbidden", status_code=status.HTTP_403_FORBIDDEN)


def _redirect_to_admin_command(command_id: int) -> RedirectResponse:
    return RedirectResponse(
        url=f"/admin/commands/{command_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _redirect_to_admin_entity(entity_type_id: int) -> RedirectResponse:
    return RedirectResponse(
        url=f"/admin/entities/{entity_type_id}",
        status_code=status.HTTP_303_SEE_OTHER,
    )


def _render(
    request: Request,
    template_name: str,
    context: Optional[dict[str, Any]] = None,
    *,
    status_code: int = status.HTTP_200_OK,
) -> HTMLResponse:
    payload = {
        "request": request,
        "csrf_token": get_csrf_token(request.cookies.get(ADMIN_COOKIE_NAME)),
        "UserRole": UserRole,
    }
    if context:
        payload.update(context)
    return templates.TemplateResponse(request, template_name, payload, status_code=status_code)


def _get_dashboard_context() -> dict[str, Any]:
    semantic_enabled = get_bool_setting("ENABLE_SEMANTIC_MATCHER", ENABLE_SEMANTIC_MATCHER)
    ollama_enabled = get_bool_setting("ENABLE_OLLAMA_FALLBACK", ENABLE_OLLAMA_FALLBACK)
    llm_mode = get_str_setting("LLM_COMMAND_MODE", LLM_COMMAND_MODE)
    ollama_model = get_str_setting("OLLAMA_MODEL", OLLAMA_MODEL)
    dynamic_sizes_enabled = get_bool_setting(
        "ALLOW_DYNAMIC_SIZE_INCHES",
        ALLOW_DYNAMIC_SIZE_INCHES,
    )
    transcription_model = get_str_setting(
        "TRANSCRIPTION_MODEL_NAME",
        TRANSCRIPTION_MODEL_NAME,
    )
    if SessionFactory is None or engine is None:
        return {
            "total_commands": 0,
            "total_examples": 0,
            "total_entities": 0,
            "pending_logs": 0,
            "active_version": None,
            "catalog_dirty": False,
            "env": ENV,
            "semantic_enabled": semantic_enabled,
            "llm_mode": llm_mode,
            "ollama_enabled": ollama_enabled,
            "ollama_model": ollama_model,
            "dynamic_sizes_enabled": dynamic_sizes_enabled,
            "transcription_model": transcription_model,
        }

    with SessionFactory(engine) as session:
        total_commands = len(session.exec(select(CommandDefinition)).all())
        total_examples = len(session.exec(select(CommandExample)).all())
        total_entities = len(session.exec(select(EntityValue)).all())
        pending_logs = len(
            session.exec(
                select(NormalizationLog).where(
                    NormalizationLog.review_status == ReviewStatus.PENDING
                )
            ).all()
        )
        active_version = session.exec(
            select(CatalogVersion)
            .where(CatalogVersion.status == CatalogStatus.ACTIVE)
            .order_by(CatalogVersion.version_number.desc())
        ).first()
        catalog_dirty = is_catalog_dirty(session)

    return {
        "total_commands": total_commands,
        "total_examples": total_examples,
        "total_entities": total_entities,
        "pending_logs": pending_logs,
        "active_version": (
            active_version.version_number if active_version is not None else None
        ),
        "catalog_dirty": catalog_dirty,
        "env": ENV,
        "semantic_enabled": semantic_enabled,
        "llm_mode": llm_mode,
        "ollama_enabled": ollama_enabled,
        "ollama_model": ollama_model,
        "dynamic_sizes_enabled": dynamic_sizes_enabled,
        "transcription_model": transcription_model,
    }


def _audit_log(
    session,
    *,
    actor_user_id: int | None,
    action: str,
    entity_type: str | None = None,
    entity_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        session.add(
            AuditLog(
                actor_user_id=actor_user_id,
                action=action,
                entity_type=entity_type,
                entity_id=entity_id,
                payload_json=payload,
            )
        )
        session.commit()
    except Exception:
        session.rollback()


def _current_role(user) -> UserRole:
    role = getattr(user, "role", UserRole.ADMIN)
    if isinstance(role, UserRole):
        return role
    return UserRole(str(role))


def _has_role(user, minimum_role: UserRole) -> bool:
    return ROLE_ORDER[_current_role(user)] >= ROLE_ORDER[minimum_role]


def _require_admin(request: Request):
    current_user = get_current_admin_user(request.cookies.get(ADMIN_COOKIE_NAME))
    if current_user is None:
        return None
    return current_user


def _require_role(request: Request, minimum_role: UserRole):
    current_user = _require_admin(request)
    if current_user is None:
        return None
    if not _has_role(current_user, minimum_role):
        return False
    return current_user


def _login_rate_limit_key(email: str, request: Request) -> str:
    client_ip = request.client.host if request.client else "unknown"
    return f"{email.strip().lower()}|{client_ip}"


def _is_login_blocked(key: str) -> bool:
    state = _LOGIN_FAILURES.get(key)
    if state is None:
        return False
    now = time.time()
    if state.get("blocked_until", 0) > now:
        return True
    if state.get("first_failed_at", 0) + LOGIN_RATE_LIMIT_WINDOW_SECONDS < now:
        _LOGIN_FAILURES.pop(key, None)
        return False
    return False


def _register_login_failure(key: str) -> None:
    now = time.time()
    state = _LOGIN_FAILURES.get(key)
    if state is None or state.get("first_failed_at", 0) + LOGIN_RATE_LIMIT_WINDOW_SECONDS < now:
        state = {"count": 0, "first_failed_at": now, "blocked_until": 0}
    state["count"] += 1
    if state["count"] >= LOGIN_RATE_LIMIT_MAX_ATTEMPTS:
        state["blocked_until"] = now + LOGIN_RATE_LIMIT_BLOCK_SECONDS
    _LOGIN_FAILURES[key] = state


def _clear_login_failures(key: str) -> None:
    _LOGIN_FAILURES.pop(key, None)


async def require_csrf(request: Request) -> None:
    session_token = request.cookies.get(ADMIN_COOKIE_NAME)
    if not session_token:
        return
    session_data = decode_session_token(session_token)
    if session_data is None:
        return
    form = await request.form()
    csrf_token = str(form.get("csrf_token") or "")
    if csrf_token != session_data.csrf_token:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token.",
        )


def _normalize_optional_text(value: str) -> Optional[str]:
    stripped = value.strip()
    return stripped or None


def _parse_optional_float(value: str) -> float | None:
    stripped = value.strip()
    if not stripped:
        return None
    return float(stripped)


def _parse_client_capabilities(value: str) -> list[str] | None:
    stripped = value.strip()
    if not stripped:
        return None
    try:
        parsed = json.loads(stripped)
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    except json.JSONDecodeError:
        pass
    capabilities = [
        item.strip()
        for chunk in stripped.splitlines()
        for item in chunk.split(",")
        if item.strip()
    ]
    return capabilities or None


def _parse_match_type(value: str) -> MatchType:
    return MatchType(value)


def _validate_entity_type_form(
    session,
    form: EntityTypeCreateForm,
    *,
    entity_type_id: int | None = None,
) -> str | None:
    code = form.code.strip()
    if not code:
        return "Entity code is required."
    if not SNAKE_CASE_PATTERN.fullmatch(code):
        return "Entity code must be snake_case."
    if not form.display_name.strip():
        return "Display name is required."
    if form.data_type not in ENTITY_DATA_TYPES:
        return "Invalid data type."

    try:
        min_value = _parse_optional_float(form.min_value)
        max_value = _parse_optional_float(form.max_value)
    except ValueError:
        return "Min and max values must be numeric."

    if (
        form.dynamic_values
        and form.data_type in {"integer", "float"}
        and min_value is not None
        and max_value is not None
        and max_value <= min_value
    ):
        return "Max value must be greater than min value."

    duplicate = session.exec(
        select(EntityType).where(
            EntityType.code == code,
            EntityType.deleted_at.is_(None),
        )
    ).first()
    if duplicate is not None and duplicate.id != entity_type_id:
        return "Entity code already exists."

    return None


def _entity_type_usage(session, entity_type_id: int) -> list[CommandDefinition]:
    return session.exec(
        select(CommandDefinition)
        .join(CommandParameter, CommandParameter.command_id == CommandDefinition.id)
        .where(CommandParameter.entity_type_id == entity_type_id)
        .where(CommandParameter.deleted_at.is_(None))
        .where(CommandDefinition.deleted_at.is_(None))
        .order_by(CommandDefinition.code)
    ).all()


def _load_command_detail_context(command_id: int) -> Optional[dict[str, Any]]:
    if SessionFactory is None or engine is None:
        return None

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return None
        examples = session.exec(
            select(CommandExample)
            .where(CommandExample.command_id == command_id)
            .order_by(CommandExample.normalized_phrase)
        ).all()
        parameters = session.exec(
            select(CommandParameter)
            .where(CommandParameter.command_id == command_id)
            .where(CommandParameter.deleted_at.is_(None))
            .order_by(CommandParameter.slot_name)
        ).all()
        entity_types = session.exec(
            select(EntityType)
            .where(EntityType.enabled.is_(True))
            .where(EntityType.deleted_at.is_(None))
            .order_by(EntityType.code)
        ).all()
        entity_type_by_id = {
            entity_type.id: entity_type
            for entity_type in entity_types
            if entity_type.id is not None
        }
        dirty = is_catalog_dirty(session)

    return {
        "command": command,
        "examples": examples,
        "parameters": parameters,
        "entity_types": entity_types,
        "entity_type_by_id": entity_type_by_id,
        "catalog_dirty": dirty,
    }


def _load_entity_detail_context(entity_type_id: int) -> Optional[dict[str, Any]]:
    if SessionFactory is None or engine is None:
        return None

    with SessionFactory(engine) as session:
        entity_type = session.get(EntityType, entity_type_id)
        if entity_type is None:
            return None
        values = session.exec(
            select(EntityValue)
            .where(EntityValue.entity_type_id == entity_type_id)
            .order_by(EntityValue.value)
        ).all()
        aliases = session.exec(
            select(EntityValueAlias).order_by(EntityValueAlias.normalized_phrase)
        ).all()
        aliases_by_value: dict[int, list[EntityValueAlias]] = {}
        for alias in aliases:
            aliases_by_value.setdefault(alias.entity_value_id, []).append(alias)
        used_by_commands = _entity_type_usage(session, entity_type_id)
        dirty = is_catalog_dirty(session)

    return {
        "entity_type": entity_type,
        "values": values,
        "aliases_by_value": aliases_by_value,
        "used_by_commands": used_by_commands,
        "catalog_dirty": dirty,
    }


def _load_settings_context() -> dict[str, Any]:
    settings: dict[str, Any] = {}
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            for key, default in EDITABLE_SETTINGS.items():
                if key in LIST_SETTINGS:
                    settings[key] = ", ".join(get_audio_list_setting(key, default))
                else:
                    settings[key] = get_runtime_setting(key, default)
            dirty = is_catalog_dirty(session)
        return {
            "settings": settings,
            "catalog_dirty": dirty,
            "setting_descriptions": SETTING_DESCRIPTIONS,
            "error": None,
        }

    return {
        "settings": {
            key: ", ".join(value) if key in LIST_SETTINGS else value
            for key, value in EDITABLE_SETTINGS.items()
        },
        "catalog_dirty": False,
        "setting_descriptions": SETTING_DESCRIPTIONS,
        "error": None,
    }


def _load_review_context(review_filter: str = "pending") -> dict[str, Any]:
    if SessionFactory is None or engine is None:
        return {
            "logs": [],
            "commands": [],
            "catalog_dirty": False,
            "review_filter": review_filter,
            "notice": None,
        }

    with SessionFactory(engine) as session:
        logs = list_review_logs(session, review_filter=review_filter)
        commands = session.exec(
            select(CommandDefinition)
            .where(CommandDefinition.enabled.is_(True))
            .order_by(CommandDefinition.code)
        ).all()
        dirty = is_catalog_dirty(session)

    return {
        "logs": logs,
        "commands": commands,
        "catalog_dirty": dirty,
        "review_filter": review_filter,
        "notice": None,
    }


def _validate_llm_settings(settings: dict[str, str]) -> Optional[str]:
    mode = settings.get("LLM_COMMAND_MODE", "").strip()
    if mode not in {"off", "fallback", "hybrid", "primary"}:
        return "LLM_COMMAND_MODE must be one of: off, fallback, hybrid, primary."

    numeric_ranges = {
        "OLLAMA_TIMEOUT_SECONDS": (1.0, 60.0),
        "LLM_ACCEPT_THRESHOLD": (0.0, 1.0),
        "LLM_CONFIDENCE_CAP": (0.0, 1.0),
    }
    for key, (minimum, maximum) in numeric_ranges.items():
        try:
            value = float(settings.get(key, ""))
        except ValueError:
            return f"{key} must be a number."
        if not minimum <= value <= maximum:
            return f"{key} must be between {minimum:g} and {maximum:g}."

    try:
        min_size = int(settings.get("MIN_SIZE_INCHES", ""))
        max_size = int(settings.get("MAX_SIZE_INCHES", ""))
    except ValueError:
        return "MIN_SIZE_INCHES and MAX_SIZE_INCHES must be integers."
    if min_size <= 0:
        return "MIN_SIZE_INCHES must be greater than 0."
    if max_size <= min_size:
        return "MAX_SIZE_INCHES must be greater than MIN_SIZE_INCHES."

    allowed_sizes = settings.get("ALLOWED_SIZE_INCHES", "")
    try:
        parsed_sizes = [
            int(item.strip())
            for item in allowed_sizes.split(",")
            if item.strip()
        ]
    except ValueError:
        return "ALLOWED_SIZE_INCHES must be a comma-separated list of integers."
    if not parsed_sizes:
        return "ALLOWED_SIZE_INCHES must include at least one size."

    return None


def _load_audio_logs_context() -> dict[str, Any]:
    if SessionFactory is None or engine is None:
        return {"logs": [], "catalog_dirty": False}

    with SessionFactory(engine) as session:
        logs = session.exec(
            select(AudioTranscriptionLog).order_by(AudioTranscriptionLog.created_at.desc())
        ).all()
        dirty = is_catalog_dirty(session)
    return {"logs": logs, "catalog_dirty": dirty}


def _load_enabled_commands() -> list[CommandDefinition]:
    if SessionFactory is None or engine is None:
        return []

    with SessionFactory(engine) as session:
        return session.exec(
            select(CommandDefinition)
            .where(CommandDefinition.enabled.is_(True))
            .order_by(CommandDefinition.code)
        ).all()


def _load_tester_context() -> dict[str, Any]:
    catalog_dirty = False
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            catalog_dirty = is_catalog_dirty(session)

    return {
        "commands": _load_enabled_commands(),
        "catalog_dirty": catalog_dirty,
        "semantic_enabled": ENABLE_SEMANTIC_MATCHER,
        "debug_data": None,
        "v2_result": None,
        "api_version": "v1",
        "text": "",
        "language_hint": "",
        "client_capabilities": "",
    }


def _load_audio_tester_context() -> dict[str, Any]:
    catalog_dirty = False
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            catalog_dirty = is_catalog_dirty(session)

    return {
        "commands": _load_enabled_commands(),
        "catalog_dirty": catalog_dirty,
        "transcription_result": None,
        "normalize_result": None,
        "debug_data": None,
        "language_hint": "",
        "context_json": "",
        "error": None,
    }


def _load_catalog_versions_context() -> dict[str, Any]:
    if SessionFactory is None or engine is None:
        return {
            "versions": [],
            "catalog_dirty": False,
            "active_version": None,
            "import_error": None,
            "import_summary": None,
            "publish_errors": None,
        }

    with SessionFactory(engine) as session:
        version_rows = session.exec(
            select(CatalogVersion).order_by(CatalogVersion.version_number.desc())
        ).all()
        versions = []
        for version in version_rows:
            snapshot = version.snapshot_json or {}
            commands = snapshot.get("commands", [])
            versions.append(
                {
                    "version": version,
                    "command_count": len(commands),
                    "example_count": sum(
                        len(item.get("examples", [])) for item in commands
                    ),
                }
            )
        return {
            "versions": versions,
            "catalog_dirty": is_catalog_dirty(session),
            "active_version": get_active_version(session),
            "import_error": None,
            "import_summary": None,
            "publish_errors": None,
        }


def _command_display_name(command_name: str) -> str:
    return command_name.replace("_", " ").title()


def _validate_catalog_yaml_payload(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict) or not isinstance(payload.get("commands"), list):
        raise ValueError("YAML must contain a root 'commands' list.")

    normalized_commands: list[dict[str, Any]] = []
    for item in payload["commands"]:
        if not isinstance(item, dict):
            raise ValueError("Each command entry must be an object.")
        command_raw = item.get("command")
        if not isinstance(command_raw, str):
            raise ValueError("Each command entry requires a string 'command'.")
        try:
            command_name = CommandName(command_raw)
        except ValueError as exc:
            raise ValueError(f"Invalid command: {command_raw}") from exc

        examples = item.get("examples", [])
        if not isinstance(examples, list):
            raise ValueError(f"'examples' must be a list for command {command_raw}.")
        clean_examples = []
        for example in examples:
            if not isinstance(example, str):
                raise ValueError(
                    f"Each example must be a string for command {command_raw}."
                )
            phrase = example.strip()
            if phrase:
                clean_examples.append(phrase)

        normalized_commands.append(
            {
                "command": command_name,
                "description": _normalize_optional_text(str(item.get("description") or "")),
                "category": _normalize_optional_text(str(item.get("category") or "")),
                "priority": int(item.get("priority", 50)),
                "examples": clean_examples,
            }
        )

    return normalized_commands


def _import_catalog_yaml(session, commands_payload: list[dict[str, Any]], actor_user_id: int | None) -> dict[str, int]:
    created_commands = 0
    added_examples = 0

    for item in commands_payload:
        command = session.exec(
            select(CommandDefinition).where(CommandDefinition.code == item["command"])
        ).first()
        if command is None:
            command = CommandDefinition(
                code=item["command"],
                display_name=_command_display_name(item["command"].value),
                description=item["description"],
                category=item["category"],
                priority=item["priority"],
                enabled=True,
            )
            session.add(command)
            session.commit()
            session.refresh(command)
            created_commands += 1
        else:
            if item["description"] is not None and not command.description:
                command.description = item["description"]
            if item["category"] is not None and not command.category:
                command.category = item["category"]
            session.add(command)
            session.commit()

        for phrase in item["examples"]:
            normalized_phrase = normalize_text(phrase)
            duplicate = session.exec(
                select(CommandExample).where(
                    CommandExample.command_id == command.id,
                    CommandExample.normalized_phrase == normalized_phrase,
                )
            ).first()
            if duplicate is not None:
                continue
            session.add(
                CommandExample(
                    command_id=command.id,
                    phrase=phrase,
                    normalized_phrase=normalized_phrase,
                    enabled=True,
                    source=ExampleSource.ADMIN,
                    match_type=MatchType.SEMANTIC,
                )
            )
            added_examples += 1
        session.commit()

    set_catalog_dirty(session, True)
    _audit_log(
        session,
        actor_user_id=actor_user_id,
        action="import_yaml",
        entity_type="catalog",
        payload={
            "created_commands": created_commands,
            "added_examples": added_examples,
            "command_count": len(commands_payload),
        },
    )
    return {
        "created_commands": created_commands,
        "added_examples": added_examples,
    }


@router.get("/admin/login", response_class=HTMLResponse)
def admin_login_page(request: Request) -> HTMLResponse:
    current_user = get_current_admin_user(request.cookies.get(ADMIN_COOKIE_NAME))
    if current_user is not None:
        return RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    return _render(request, "login.html", {"error": None})


@router.post("/admin/login", response_class=HTMLResponse)
def admin_login_submit(
    request: Request,
    form: LoginForm = Depends(LoginForm.as_form),
) -> HTMLResponse:
    rate_limit_key = _login_rate_limit_key(form.email, request)
    if _is_login_blocked(rate_limit_key):
        return _render(
            request,
            "login.html",
            {
                "error": "Too many failed login attempts. Try again later.",
                "email": form.email,
            },
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    user = authenticate_admin_user(form.email, form.password)
    if user is None:
        _register_login_failure(rate_limit_key)
        if SessionFactory is not None and engine is not None:
            with SessionFactory(engine) as session:
                _audit_log(
                    session,
                    actor_user_id=None,
                    action="login_failed",
                    entity_type="admin_user",
                    payload={"email": form.email, "ip": request.client.host if request.client else None},
                )
        return _render(
            request,
            "login.html",
            {
                "error": "Invalid email or password.",
                "email": form.email,
            },
            status_code=status.HTTP_401_UNAUTHORIZED,
        )

    _clear_login_failures(rate_limit_key)
    response = RedirectResponse(url="/admin", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=create_session_token(user),
        max_age=ADMIN_SESSION_MAX_AGE_SECONDS,
        secure=ENV == "production",
        httponly=True,
        samesite="lax",
    )
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            _audit_log(
                session,
                actor_user_id=user.id,
                action="login_success",
                entity_type="admin_user",
                entity_id=user.id,
                payload={"email": user.email, "ip": request.client.host if request.client else None},
            )
    return response


@router.post("/admin/logout")
async def admin_logout(
    request: Request,
    _: None = Depends(require_csrf),
) -> RedirectResponse:
    response = RedirectResponse(url="/admin/login", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(ADMIN_COOKIE_NAME)
    return response


@router.get("/admin", response_class=HTMLResponse)
def admin_dashboard(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    return _render(
        request,
        "dashboard.html",
        {
            "current_user": current_user,
            "dashboard": _get_dashboard_context(),
        },
    )


@router.get("/admin/catalog/versions", response_class=HTMLResponse)
def admin_catalog_versions(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    context = _load_catalog_versions_context()
    context["current_user"] = current_user
    return _render(request, "catalog_versions.html", context)


@router.post("/admin/catalog/publish")
async def admin_catalog_publish(
    request: Request,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(
            url="/admin/catalog/versions",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    with SessionFactory(engine) as session:
        result = publish_catalog(session, actor_user_id=getattr(current_user, "id", None))
        if not result.get("published"):
            context = _load_catalog_versions_context()
            context["current_user"] = current_user
            context["publish_errors"] = result.get("errors", [])
            return _render(
                request,
                "catalog_versions.html",
                context,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    return RedirectResponse(
        url="/admin/catalog/versions",
        status_code=status.HTTP_303_SEE_OTHER,
    )


@router.get("/admin/catalog/export-yaml")
def admin_catalog_export_yaml(request: Request):
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    with SessionFactory(engine) as session:
        payload = export_catalog_to_yaml_shape(session)

    yaml_content = yaml.safe_dump(
        payload,
        allow_unicode=True,
        sort_keys=False,
    )
    headers = {"Content-Disposition": 'attachment; filename="catalog-export.yml"'}
    return Response(content=yaml_content, media_type="application/x-yaml", headers=headers)


@router.post("/admin/catalog/import-yaml", response_class=HTMLResponse)
async def admin_catalog_import_yaml(request: Request):
    await require_csrf(request)
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(
            url="/admin/catalog/versions",
            status_code=status.HTTP_303_SEE_OTHER,
        )

    form = await request.form()
    upload = form.get("catalog_file")
    context = _load_catalog_versions_context()
    context["current_user"] = current_user

    if upload is None or not hasattr(upload, "file"):
        context["import_error"] = "Please upload a YAML file."
        return _render(
            request,
            "catalog_versions.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        raw_bytes = await upload.read()
        payload = yaml.safe_load(raw_bytes.decode("utf-8"))
        commands_payload = _validate_catalog_yaml_payload(payload)
        with SessionFactory(engine) as session:
            summary = _import_catalog_yaml(
                session,
                commands_payload,
                getattr(current_user, "id", None),
            )
        context = _load_catalog_versions_context()
        context["current_user"] = current_user
        context["import_summary"] = summary
        return _render(request, "catalog_versions.html", context)
    except (ValueError, yaml.YAMLError, UnicodeDecodeError) as exc:
        context["import_error"] = str(exc)
        return _render(
            request,
            "catalog_versions.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


@router.get("/admin/commands", response_class=HTMLResponse)
def admin_commands_list(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    commands: list[dict[str, Any]] = []
    catalog_dirty = False
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            command_rows = session.exec(
                select(CommandDefinition).order_by(CommandDefinition.priority.desc(), CommandDefinition.code)
            ).all()
            examples = session.exec(select(CommandExample)).all()
            example_counts: dict[int, int] = {}
            for example in examples:
                example_counts[example.command_id] = example_counts.get(example.command_id, 0) + 1
            commands = [
                {"command": item, "example_count": example_counts.get(item.id or 0, 0)}
                for item in command_rows
            ]
            catalog_dirty = is_catalog_dirty(session)

    return _render(
        request,
        "commands.html",
        {
            "current_user": current_user,
            "commands": commands,
            "catalog_dirty": catalog_dirty,
        },
    )


def _command_form_context(
    request: Request,
    current_user,
    *,
    form: CommandCreateForm | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "current_user": current_user,
        "form": form
        or CommandCreateForm(
            code="",
            display_name="",
            description="",
            category="",
            client_action_key="",
            enabled=True,
            priority=50,
            min_confidence=0.72,
        ),
        "error": error,
        "catalog_dirty": False,
    }


def _validate_custom_command_form(session, form: CommandCreateForm) -> str | None:
    code = form.code.strip()
    client_action_key = form.client_action_key.strip()
    display_name = form.display_name.strip()

    if not code:
        return "Code is required."
    if not CUSTOM_COMMAND_CODE_PATTERN.fullmatch(code):
        return "Code must use uppercase letters, numbers, and underscores."
    if code == CommandName.UNKNOWN.value:
        return "UNKNOWN is reserved and cannot be used as a custom command."
    if code in {command.value for command in CommandName}:
        return "Code conflicts with a protected core command."
    if not display_name:
        return "Display name is required."
    if not client_action_key:
        return "Client action key is required."
    if not CLIENT_ACTION_KEY_PATTERN.fullmatch(client_action_key):
        return "Client action key must be snake_case."

    duplicate = session.exec(
        select(CommandDefinition).where(CommandDefinition.code == code)
    ).first()
    if duplicate is not None:
        return "Code already exists."

    return None


def _render_command_detail_error(
    request: Request,
    current_user,
    command_id: int,
    message: str,
) -> HTMLResponse:
    context = _load_command_detail_context(command_id)
    if context is None:
        return _render(
            request,
            "command_detail.html",
            {
                "current_user": current_user,
                "command": None,
                "examples": [],
                "catalog_dirty": False,
                "error": "Command not found.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )
    context["current_user"] = current_user
    context["error"] = message
    return _render(
        request,
        "command_detail.html",
        context,
        status_code=status.HTTP_400_BAD_REQUEST,
    )


@router.get("/admin/commands/new", response_class=HTMLResponse)
def admin_command_new(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    return _render(
        request,
        "command_new.html",
        _command_form_context(request, current_user),
    )


@router.post("/admin/commands/new")
async def admin_command_create(
    request: Request,
    form: CommandCreateForm = Depends(CommandCreateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _render(
            request,
            "command_new.html",
            _command_form_context(
                request,
                current_user,
                form=form,
                error="Database is unavailable.",
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    with SessionFactory(engine) as session:
        error = _validate_custom_command_form(session, form)
        if error is not None:
            return _render(
                request,
                "command_new.html",
                _command_form_context(request, current_user, form=form, error=error),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        command = CommandDefinition(
            code=form.code.strip(),
            display_name=form.display_name.strip(),
            description=_normalize_optional_text(form.description),
            category=_normalize_optional_text(form.category),
            enabled=form.enabled,
            priority=form.priority,
            min_confidence=form.min_confidence,
            command_type="custom",
            status="draft",
            protected=False,
            client_action_key=form.client_action_key.strip(),
            created_by=getattr(current_user, "id", None),
            updated_by=getattr(current_user, "id", None),
        )
        session.add(command)
        session.commit()
        session.refresh(command)
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="custom_command_create",
            entity_type="command_definition",
            entity_id=command.id,
            payload={
                "code": command.code,
                "client_action_key": command.client_action_key,
            },
        )
        command_id = command.id

    return _redirect_to_admin_command(command_id)


@router.get("/admin/commands/{command_id}", response_class=HTMLResponse)
def admin_command_detail(request: Request, command_id: int) -> HTMLResponse:
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    context = _load_command_detail_context(command_id)
    if context is None:
        return _render(
            request,
            "command_detail.html",
            {
                "current_user": current_user,
                "command": None,
                "examples": [],
                "catalog_dirty": False,
                "error": "Command not found.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    context["current_user"] = current_user
    context["error"] = None
    return _render(request, "command_detail.html", context)


@router.get("/admin/entities", response_class=HTMLResponse)
def admin_entities_list(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    entity_types: list[dict[str, Any]] = []
    catalog_dirty = False
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            types = session.exec(
                select(EntityType)
                .where(EntityType.deleted_at.is_(None))
                .order_by(EntityType.code)
            ).all()
            values = session.exec(select(EntityValue)).all()
            value_counts: dict[int, int] = {}
            for value in values:
                value_counts[value.entity_type_id] = value_counts.get(value.entity_type_id, 0) + 1
            usage_counts: dict[int, int] = {}
            parameters = session.exec(
                select(CommandParameter).where(CommandParameter.deleted_at.is_(None))
            ).all()
            for parameter in parameters:
                usage_counts[parameter.entity_type_id] = (
                    usage_counts.get(parameter.entity_type_id, 0) + 1
                )
            entity_types = [
                {
                    "entity_type": item,
                    "value_count": value_counts.get(item.id or 0, 0),
                    "used_by_commands": usage_counts.get(item.id or 0, 0),
                }
                for item in types
            ]
            catalog_dirty = is_catalog_dirty(session)

    return _render(
        request,
        "entities.html",
        {
            "current_user": current_user,
            "entity_types": entity_types,
            "catalog_dirty": catalog_dirty,
        },
    )


@router.get("/admin/entities/new", response_class=HTMLResponse)
def admin_entity_new_page(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    catalog_dirty = False
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            catalog_dirty = is_catalog_dirty(session)

    return _render(
        request,
        "entity_new.html",
        {
            "current_user": current_user,
            "catalog_dirty": catalog_dirty,
            "data_types": sorted(ENTITY_DATA_TYPES),
            "error": None,
        },
    )


@router.post("/admin/entities/new")
async def admin_entity_create(
    request: Request,
    form: EntityTypeCreateForm = Depends(EntityTypeCreateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        error = _validate_entity_type_form(session, form)
        if error is not None:
            return _render(
                request,
                "entity_new.html",
                {
                    "current_user": current_user,
                    "catalog_dirty": is_catalog_dirty(session),
                    "data_types": sorted(ENTITY_DATA_TYPES),
                    "error": error,
                    "form": form,
                },
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        entity_type = EntityType(
            code=form.code.strip(),
            display_name=form.display_name.strip(),
            description=_normalize_optional_text(form.description),
            data_type=form.data_type,
            unit=_normalize_optional_text(form.unit),
            dynamic_values=form.dynamic_values,
            min_value=_parse_optional_float(form.min_value),
            max_value=_parse_optional_float(form.max_value),
            protected=False,
            enabled=True,
        )
        session.add(entity_type)
        session.commit()
        session.refresh(entity_type)
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="entity_type_create",
            entity_type="entity_type",
            entity_id=entity_type.id,
            payload={"code": entity_type.code},
        )
        entity_type_id = entity_type.id

    return _redirect_to_admin_entity(entity_type_id)


@router.get("/admin/entities/{entity_type_id}", response_class=HTMLResponse)
def admin_entity_detail(request: Request, entity_type_id: int) -> HTMLResponse:
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    context = _load_entity_detail_context(entity_type_id)
    if context is None:
        return _render(
            request,
            "entity_detail.html",
            {
                "current_user": current_user,
                "entity_type": None,
                "values": [],
                "aliases_by_value": {},
                "catalog_dirty": False,
                "error": "Entity type not found.",
            },
            status_code=status.HTTP_404_NOT_FOUND,
        )

    context["current_user"] = current_user
    context["error"] = None
    return _render(request, "entity_detail.html", context)


@router.get("/admin/settings", response_class=HTMLResponse)
def admin_settings_page(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    context = _load_settings_context()
    context["current_user"] = current_user
    return _render(request, "settings.html", context)


@router.post("/admin/settings/update")
async def admin_settings_update(request: Request):
    await require_csrf(request)
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/settings", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    new_values: dict[str, str] = {}
    for key, default in EDITABLE_SETTINGS.items():
        raw_value = form.get(key)
        if isinstance(default, bool):
            new_values[key] = "true" if raw_value in {"true", "on", "1", "yes"} else "false"
        elif isinstance(default, list):
            new_values[key] = (
                ", ".join(
                    [item.strip() for item in str(raw_value or "").split(",") if item.strip()]
                )
                if raw_value is not None
                else ", ".join(str(item) for item in default)
            )
        elif raw_value is None:
            new_values[key] = str(default)
        else:
            new_values[key] = str(raw_value).strip()

    validation_error = _validate_llm_settings(new_values)
    if validation_error is not None:
        context = _load_settings_context()
        context["settings"].update(new_values)
        context["current_user"] = current_user
        context["error"] = validation_error
        return _render(
            request,
            "settings.html",
            context,
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    with SessionFactory(engine) as session:
        dirty_changed = False
        changed_keys: list[str] = []
        changed_audio_keys: list[str] = []
        changed_llm_keys: list[str] = []
        audio_model_reload_required = False
        llm_restart_required = False
        llm_runtime_refresh_required = False
        for key, default in EDITABLE_SETTINGS.items():
            new_value = new_values[key]

            setting = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
            previous_value = (
                setting.value
                if setting is not None
                else (", ".join(str(item) for item in default) if isinstance(default, list) else str(default))
            )
            if setting is None:
                setting = AppSetting(key=key, value=new_value)
                session.add(setting)
            else:
                setting.value = new_value
                session.add(setting)

            if str(previous_value) != str(new_value):
                changed_keys.append(key)
            if key in MATCHING_SETTINGS and str(previous_value) != str(new_value):
                dirty_changed = True
            if key in AUDIO_SETTINGS_KEYS and str(previous_value) != str(new_value):
                changed_audio_keys.append(key)
            if key in AUDIO_MODEL_RELOAD_SETTINGS and str(previous_value) != str(new_value):
                audio_model_reload_required = True
            if key in LLM_SETTINGS_KEYS and str(previous_value) != str(new_value):
                changed_llm_keys.append(key)
            if key in LLM_RUNTIME_REFRESH_SETTINGS and str(previous_value) != str(new_value):
                llm_runtime_refresh_required = True
            if key in LLM_RESTART_REQUIRED_SETTINGS and str(previous_value) != str(new_value):
                llm_restart_required = True

        if audio_model_reload_required:
            reload_setting = session.exec(
                select(AppSetting).where(AppSetting.key == "AUDIO_MODEL_RELOAD_REQUIRED")
            ).first()
            if reload_setting is None:
                session.add(AppSetting(key="AUDIO_MODEL_RELOAD_REQUIRED", value="true"))
            else:
                reload_setting.value = "true"
                session.add(reload_setting)

        session.commit()
        if dirty_changed:
            set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="settings_update",
            entity_type="app_setting",
            payload={"keys": changed_keys, "dirty_changed": dirty_changed},
        )
        if changed_audio_keys:
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="audio_settings_update",
                entity_type="app_setting",
                payload={
                    "keys": changed_audio_keys,
                    "model_reload_required": audio_model_reload_required,
                },
            )
        if changed_llm_keys:
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="llm_settings_update",
                entity_type="app_setting",
                payload={
                    "keys": changed_llm_keys,
                    "runtime_refresh_required": llm_runtime_refresh_required,
                    "restart_required": llm_restart_required,
                },
            )

    return RedirectResponse(url="/admin/settings", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/admin/review", response_class=HTMLResponse)
def admin_review_page(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    review_filter = str(request.query_params.get("filter") or "pending")
    context = _load_review_context(review_filter=review_filter)
    context["current_user"] = current_user
    return _render(request, "review.html", context)


@router.get("/admin/tester", response_class=HTMLResponse)
def admin_tester_page(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    context = _load_tester_context()
    context["current_user"] = current_user
    return _render(request, "tester.html", context)


@router.get("/admin/audio-logs", response_class=HTMLResponse)
def admin_audio_logs_page(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    context = _load_audio_logs_context()
    context["current_user"] = current_user
    return _render(request, "audio_logs.html", context)


@router.get("/admin/audio-tester", response_class=HTMLResponse)
def admin_audio_tester_page(request: Request) -> HTMLResponse:
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    context = _load_audio_tester_context()
    context["current_user"] = current_user
    return _render(request, "audio_tester.html", context)


@router.post("/admin/tester/run", response_class=HTMLResponse)
async def admin_tester_run(request: Request) -> HTMLResponse:
    await require_csrf(request)
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    form = await request.form()
    text = str(form.get("text") or "")
    language_hint = str(form.get("language_hint") or "").strip() or None
    api_version = str(form.get("api_version") or "v1").strip() or "v1"
    client_capabilities_raw = str(form.get("client_capabilities") or "").strip()
    client_capabilities = _parse_client_capabilities(client_capabilities_raw)
    payload = NormalizeRequest(text=text, language_hint=language_hint, context=None)

    context = _load_tester_context()
    debug_data = build_debug_response(payload) if api_version == "v1" else None
    v2_result = None
    if api_version == "v2":
        v2_result = normalize_command_text_v2(
            text=text,
            language_hint=language_hint,
            context=None,
            client_capabilities=client_capabilities,
        ).model_dump(mode="json")
    context.update(
        {
            "current_user": current_user,
            "text": text,
            "language_hint": language_hint or "",
            "api_version": api_version,
            "client_capabilities": client_capabilities_raw,
            "debug_data": debug_data,
            "v2_result": v2_result,
        }
    )
    return _render(request, "tester.html", context)


@router.post("/admin/audio-tester/transcribe", response_class=HTMLResponse)
async def admin_audio_tester_transcribe(request: Request) -> HTMLResponse:
    await require_csrf(request)
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    form = await request.form()
    upload_file = form.get("file")
    language_hint = str(form.get("language_hint") or "").strip() or None

    context = _load_audio_tester_context()
    context.update(
        {
            "current_user": current_user,
            "language_hint": language_hint or "",
            "context_json": str(form.get("context_json") or ""),
        }
    )

    if upload_file is None or not hasattr(upload_file, "filename"):
        context["error"] = "Audio file is required."
        return _render(request, "audio_tester.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        context["transcription_result"] = process_audio_transcription_upload(
            upload_file,
            language_hint=language_hint,
        ).model_dump(mode="json")
        return _render(request, "audio_tester.html", context)
    except Exception as exc:
        context["error"] = str(exc)
        return _render(request, "audio_tester.html", context, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/admin/audio-tester/normalize", response_class=HTMLResponse)
async def admin_audio_tester_normalize(request: Request) -> HTMLResponse:
    await require_csrf(request)
    current_user = _require_role(request, UserRole.VIEWER)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()

    form = await request.form()
    upload_file = form.get("file")
    language_hint = str(form.get("language_hint") or "").strip() or None
    context_json = str(form.get("context_json") or "").strip() or None

    context = _load_audio_tester_context()
    context.update(
        {
            "current_user": current_user,
            "language_hint": language_hint or "",
            "context_json": context_json or "",
        }
    )

    if upload_file is None or not hasattr(upload_file, "filename"):
        context["error"] = "Audio file is required."
        return _render(request, "audio_tester.html", context, status_code=status.HTTP_400_BAD_REQUEST)

    try:
        context["normalize_result"] = process_audio_normalization_upload(
            upload_file,
            language_hint=language_hint,
            context_json=context_json,
        ).model_dump(mode="json")
        context["transcription_result"] = context["normalize_result"]["transcription"]
        transcription_text = str(context["transcription_result"].get("text") or "")
        context["debug_data"] = build_debug_response(
            NormalizeRequest(
                text=transcription_text,
                language_hint=language_hint
                or context["transcription_result"].get("language"),
                context=None,
            )
        )
        return _render(request, "audio_tester.html", context)
    except Exception as exc:
        context["error"] = str(exc)
        return _render(request, "audio_tester.html", context, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/admin/tester/save-example")
async def admin_tester_save_example(request: Request):
    await require_csrf(request)
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/tester", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    return_to = str(form.get("return_to") or "").strip()
    redirect_url = "/admin/audio-tester" if return_to == "audio-tester" else "/admin/tester"
    phrase = str(form.get("phrase") or "").strip()
    if not phrase:
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    command_id_raw = form.get("command_id")
    if command_id_raw is None:
        return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

    command_id = int(command_id_raw)
    normalized_phrase = normalize_text(phrase)
    language = _normalize_optional_text(str(form.get("language") or ""))
    match_type = _parse_match_type(str(form.get("match_type") or MatchType.SEMANTIC.value))

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)

        duplicate = session.exec(
            select(CommandExample).where(
                CommandExample.command_id == command_id,
                CommandExample.normalized_phrase == normalized_phrase,
            )
        ).first()
        if duplicate is None:
            session.add(
                CommandExample(
                    command_id=command_id,
                    phrase=phrase,
                    normalized_phrase=normalized_phrase,
                    language=language,
                    match_type=match_type,
                    enabled=True,
                    source=ExampleSource.ADMIN,
                )
            )
            session.commit()
            set_catalog_dirty(session, True)
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="example_create",
                entity_type="command_example",
                payload={"command_id": command_id, "phrase": phrase},
            )

    return RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/review/{log_id}/assign")
async def admin_review_assign(request: Request, log_id: int):
    await require_csrf(request)
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/review", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    command_id = int(form.get("command_id"))
    match_type = str(form.get("match_type") or "semantic")
    language = str(form.get("language") or "").strip() or None

    with SessionFactory(engine) as session:
        assign_log_to_command(
            session,
            log_id=log_id,
            command_id=command_id,
            match_type=match_type,
            language=language,
        )

    return RedirectResponse(url="/admin/review", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/review/{log_id}/ignore")
async def admin_review_ignore(
    request: Request,
    log_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/review", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        ignore_review_log(session, log_id=log_id)

    return RedirectResponse(url="/admin/review", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/review/bulk")
async def admin_review_bulk(
    request: Request,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/review", status_code=status.HTTP_303_SEE_OTHER)

    form = await request.form()
    log_ids = [
        int(value)
        for value in form.getlist("log_ids")
        if str(value).isdigit()
    ]
    action = str(form.get("bulk_action") or "").strip()
    if not log_ids:
        return RedirectResponse(url="/admin/review", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        if action == "ignore":
            ignore_review_logs(session, log_ids=log_ids)
        elif action == "convert":
            command_id_raw = form.get("command_id")
            if command_id_raw is not None and str(command_id_raw).isdigit():
                assign_logs_to_command(
                    session,
                    log_ids=log_ids,
                    command_id=int(command_id_raw),
                    match_type=str(form.get("match_type") or "semantic"),
                    language=str(form.get("language") or "").strip() or None,
                )

    return RedirectResponse(url="/admin/review", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/commands/{command_id}/update")
async def admin_command_update(
    request: Request,
    command_id: int,
    form: CommandUpdateForm = Depends(CommandUpdateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _redirect_to_admin_command(command_id)

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return _redirect_to_admin_command(command_id)
        command.display_name = form.display_name.strip()
        command.description = _normalize_optional_text(form.description)
        command.category = _normalize_optional_text(form.category)
        command.enabled = form.enabled
        command.priority = form.priority
        command.min_confidence = form.min_confidence
        session.add(command)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_update",
            entity_type="command_definition",
            entity_id=command_id,
            payload={"display_name": command.display_name},
        )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/commands/{command_id}/disable")
async def admin_command_disable(
    request: Request,
    command_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _redirect_to_admin_command(command_id)

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return _redirect_to_admin_command(command_id)
        command.status = "disabled"
        command.enabled = False
        command.updated_by = getattr(current_user, "id", None)
        session.add(command)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_disable",
            entity_type="command_definition",
            entity_id=command_id,
            payload={"code": command.code},
        )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/commands/{command_id}/deprecate")
async def admin_command_deprecate(
    request: Request,
    command_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _redirect_to_admin_command(command_id)

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return _redirect_to_admin_command(command_id)
        command.status = "deprecated"
        command.enabled = False
        command.updated_by = getattr(current_user, "id", None)
        session.add(command)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_deprecate",
            entity_type="command_definition",
            entity_id=command_id,
            payload={"code": command.code},
        )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/commands/{command_id}/delete")
async def admin_command_delete(
    request: Request,
    command_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.ADMIN)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _redirect_to_admin_command(command_id)

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return _redirect_to_admin_command(command_id)
        if (
            command.protected
            or command.command_type != "custom"
            or command.status != "draft"
        ):
            return _render_command_detail_error(
                request,
                current_user,
                command_id,
                "Only unprotected custom draft commands can be hard deleted.",
            )

        code = command.code
        session.delete(command)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_delete",
            entity_type="command_definition",
            entity_id=command_id,
            payload={"code": code},
        )

    return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)


def _validate_command_parameter_form(
    session,
    form: CommandParameterCreateForm,
    *,
    command_id: int,
    parameter_id: int | None = None,
) -> str | None:
    slot_name = form.slot_name.strip()
    target_field = form.target_field.strip()
    if not slot_name:
        return "Slot name is required."
    if not SNAKE_CASE_PATTERN.fullmatch(slot_name):
        return "Slot name must be snake_case."
    if not target_field:
        return "Target field is required."
    if not SNAKE_CASE_PATTERN.fullmatch(target_field):
        return "Target field must be snake_case."

    entity_type = session.get(EntityType, form.entity_type_id)
    if (
        entity_type is None
        or not entity_type.enabled
        or entity_type.deleted_at is not None
    ):
        return "Entity type must exist and be enabled."

    duplicate_query = select(CommandParameter).where(
        CommandParameter.command_id == command_id,
        CommandParameter.slot_name == slot_name,
        CommandParameter.deleted_at.is_(None),
    )
    duplicate = session.exec(duplicate_query).first()
    if duplicate is not None and duplicate.id != parameter_id:
        return "Parameter slot_name already exists for this command."

    return None


@router.post("/admin/commands/{command_id}/parameters")
async def admin_command_add_parameter(
    request: Request,
    command_id: int,
    form: CommandParameterCreateForm = Depends(CommandParameterCreateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _redirect_to_admin_command(command_id)

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return _redirect_to_admin_command(command_id)
        error = _validate_command_parameter_form(session, form, command_id=command_id)
        if error is not None:
            return _render_command_detail_error(request, current_user, command_id, error)

        parameter = CommandParameter(
            command_id=command_id,
            slot_name=form.slot_name.strip(),
            entity_type_id=form.entity_type_id,
            target_field=form.target_field.strip(),
            required=form.required,
            allow_multiple=form.allow_multiple,
            default_value=_normalize_optional_text(form.default_value),
            description=_normalize_optional_text(form.description),
            extraction_hint=_normalize_optional_text(form.extraction_hint),
        )
        session.add(parameter)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_parameter_create",
            entity_type="command_parameter",
            entity_id=parameter.id,
            payload={"command_id": command_id, "slot_name": parameter.slot_name},
        )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/command-parameters/{parameter_id}/update")
async def admin_command_parameter_update(
    request: Request,
    parameter_id: int,
    form: CommandParameterUpdateForm = Depends(CommandParameterUpdateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        parameter = session.get(CommandParameter, parameter_id)
        if parameter is None or parameter.deleted_at is not None:
            return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)
        command_id = parameter.command_id
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)
        error = _validate_command_parameter_form(
            session,
            form,
            command_id=command_id,
            parameter_id=parameter_id,
        )
        if error is not None:
            return _render_command_detail_error(request, current_user, command_id, error)

        parameter.slot_name = form.slot_name.strip()
        parameter.entity_type_id = form.entity_type_id
        parameter.target_field = form.target_field.strip()
        parameter.required = form.required
        parameter.allow_multiple = form.allow_multiple
        parameter.default_value = _normalize_optional_text(form.default_value)
        parameter.description = _normalize_optional_text(form.description)
        parameter.extraction_hint = _normalize_optional_text(form.extraction_hint)
        session.add(parameter)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_parameter_update",
            entity_type="command_parameter",
            entity_id=parameter_id,
            payload={"command_id": command_id, "slot_name": parameter.slot_name},
        )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/command-parameters/{parameter_id}/delete")
async def admin_command_parameter_delete(
    request: Request,
    parameter_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        parameter = session.get(CommandParameter, parameter_id)
        if parameter is None:
            return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)
        command_id = parameter.command_id
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)

        if command.protected and parameter.required:
            return _render_command_detail_error(
                request,
                current_user,
                command_id,
                "Required parameters for protected core commands cannot be deleted.",
            )

        slot_name = parameter.slot_name
        if command.command_type == "custom" and command.status == "draft":
            session.delete(parameter)
        else:
            parameter.deleted_at = utc_now()
            session.add(parameter)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_parameter_delete",
            entity_type="command_parameter",
            entity_id=parameter_id,
            payload={"command_id": command_id, "slot_name": slot_name},
        )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/commands/{command_id}/examples")
async def admin_command_add_example(
    request: Request,
    command_id: int,
    form: ExampleCreateForm = Depends(ExampleCreateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _redirect_to_admin_command(command_id)

    phrase = form.phrase.strip()
    if not phrase:
        return _redirect_to_admin_command(command_id)
    normalized_phrase = normalize_text(phrase)

    with SessionFactory(engine) as session:
        command = session.get(CommandDefinition, command_id)
        if command is None:
            return _redirect_to_admin_command(command_id)

        duplicate = session.exec(
            select(CommandExample).where(
                CommandExample.command_id == command_id,
                CommandExample.normalized_phrase == normalized_phrase,
            )
        ).first()
        if duplicate is None:
            session.add(
                CommandExample(
                    command_id=command_id,
                    phrase=phrase,
                    normalized_phrase=normalized_phrase,
                    language=_normalize_optional_text(form.language),
                    match_type=_parse_match_type(form.match_type),
                    enabled=form.enabled,
                    source=ExampleSource.ADMIN,
                )
            )
            session.commit()
            set_catalog_dirty(session, True)
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="example_create",
                entity_type="command_example",
                entity_id=command.id,
                payload={"command_id": command_id, "phrase": phrase},
            )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/entities/{entity_type_id}/values")
async def admin_entity_add_value(
    request: Request,
    entity_type_id: int,
    form: EntityValueCreateForm = Depends(EntityValueCreateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return _redirect_to_admin_entity(entity_type_id)

    value_text = form.value.strip()
    if not value_text:
        return _redirect_to_admin_entity(entity_type_id)

    with SessionFactory(engine) as session:
        entity_type = session.get(EntityType, entity_type_id)
        if entity_type is None:
            return _redirect_to_admin_entity(entity_type_id)
        duplicate = session.exec(
            select(EntityValue).where(
                EntityValue.entity_type_id == entity_type_id,
                EntityValue.value == value_text,
            )
        ).first()
        if duplicate is None:
            session.add(
                EntityValue(
                    entity_type_id=entity_type_id,
                    value=value_text,
                    label=_normalize_optional_text(form.label),
                    enabled=form.enabled,
                )
            )
            session.commit()
            set_catalog_dirty(session, True)
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="entity_update",
                entity_type="entity_value",
                payload={"entity_type_id": entity_type_id, "value": value_text},
            )

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/entities/{entity_type_id}/disable")
async def admin_entity_type_disable(
    request: Request,
    entity_type_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        entity_type = session.get(EntityType, entity_type_id)
        if entity_type is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        if entity_type.protected:
            context = _load_entity_detail_context(entity_type_id) or {}
            context.update(
                {
                    "current_user": current_user,
                    "error": "Protected entity types cannot be disabled.",
                }
            )
            return _render(
                request,
                "entity_detail.html",
                context,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        used_by_commands = _entity_type_usage(session, entity_type_id)
        if used_by_commands:
            context = _load_entity_detail_context(entity_type_id) or {}
            context.update(
                {
                    "current_user": current_user,
                    "error": "Entity type is used by active command parameters.",
                }
            )
            return _render(
                request,
                "entity_detail.html",
                context,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        entity_type.enabled = False
        session.add(entity_type)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="entity_type_disable",
            entity_type="entity_type",
            entity_id=entity_type_id,
            payload={"code": entity_type.code},
        )

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/entities/{entity_type_id}/delete")
async def admin_entity_type_delete(
    request: Request,
    entity_type_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        entity_type = session.get(EntityType, entity_type_id)
        if entity_type is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        if entity_type.protected:
            context = _load_entity_detail_context(entity_type_id) or {}
            context.update(
                {
                    "current_user": current_user,
                    "error": "Protected entity types cannot be deleted.",
                }
            )
            return _render(
                request,
                "entity_detail.html",
                context,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        used_by_commands = _entity_type_usage(session, entity_type_id)
        if used_by_commands:
            context = _load_entity_detail_context(entity_type_id) or {}
            context.update(
                {
                    "current_user": current_user,
                    "error": "Entity type is used by active command parameters.",
                }
            )
            return _render(
                request,
                "entity_detail.html",
                context,
                status_code=status.HTTP_400_BAD_REQUEST,
            )

        entity_type.enabled = False
        entity_type.deleted_at = utc_now()
        session.add(entity_type)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="entity_type_delete",
            entity_type="entity_type",
            entity_id=entity_type_id,
            payload={"code": entity_type.code},
        )

    return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)


@router.post("/admin/entity-values/{value_id}/update")
async def admin_entity_value_update(
    request: Request,
    value_id: int,
    form: EntityValueUpdateForm = Depends(EntityValueUpdateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        value = session.get(EntityValue, value_id)
        if value is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        if form.value.strip():
            value.value = form.value.strip()
        value.label = _normalize_optional_text(form.label)
        value.enabled = form.enabled
        session.add(value)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="entity_update",
            entity_type="entity_value",
            entity_id=value_id,
            payload={"value": value.value, "enabled": value.enabled},
        )
        entity_type_id = value.entity_type_id

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/entity-values/{value_id}/delete")
async def admin_entity_value_delete(
    request: Request,
    value_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        value = session.get(EntityValue, value_id)
        if value is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        value.enabled = False
        entity_type_id = value.entity_type_id
        session.add(value)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="entity_update",
            entity_type="entity_value",
            entity_id=value_id,
            payload={"enabled": False},
        )

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/entity-values/{value_id}/aliases")
async def admin_entity_add_alias(
    request: Request,
    value_id: int,
    form: EntityAliasCreateForm = Depends(EntityAliasCreateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    phrase = form.phrase.strip()
    if not phrase:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
    normalized_phrase = normalize_text(phrase)

    with SessionFactory(engine) as session:
        value = session.get(EntityValue, value_id)
        if value is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        duplicate = session.exec(
            select(EntityValueAlias).where(
                EntityValueAlias.entity_value_id == value_id,
                EntityValueAlias.normalized_phrase == normalized_phrase,
            )
        ).first()
        if duplicate is None:
            session.add(
                EntityValueAlias(
                    entity_value_id=value_id,
                    phrase=phrase,
                    normalized_phrase=normalized_phrase,
                    language=_normalize_optional_text(form.language),
                    enabled=form.enabled,
                )
            )
            session.commit()
            set_catalog_dirty(session, True)
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="entity_update",
                entity_type="entity_alias",
                payload={"value_id": value_id, "phrase": phrase},
            )
        entity_type_id = value.entity_type_id

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/entity-aliases/{alias_id}/update")
async def admin_entity_alias_update(
    request: Request,
    alias_id: int,
    form: EntityAliasUpdateForm = Depends(EntityAliasUpdateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        alias = session.get(EntityValueAlias, alias_id)
        if alias is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        phrase = form.phrase.strip()
        entity_type_id = session.get(EntityValue, alias.entity_value_id).entity_type_id
        if not phrase:
            return _redirect_to_admin_entity(entity_type_id)
        normalized_phrase = normalize_text(phrase)
        duplicate = session.exec(
            select(EntityValueAlias).where(
                EntityValueAlias.entity_value_id == alias.entity_value_id,
                EntityValueAlias.normalized_phrase == normalized_phrase,
                EntityValueAlias.id != alias.id,
            )
        ).first()
        if duplicate is None:
            alias.phrase = phrase
            alias.normalized_phrase = normalized_phrase
            alias.language = _normalize_optional_text(form.language)
            alias.enabled = form.enabled
            session.add(alias)
            session.commit()
            set_catalog_dirty(session, True)
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="entity_update",
                entity_type="entity_alias",
                entity_id=alias_id,
                payload={"phrase": phrase, "enabled": alias.enabled},
            )

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/entity-aliases/{alias_id}/delete")
async def admin_entity_alias_delete(
    request: Request,
    alias_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        alias = session.get(EntityValueAlias, alias_id)
        if alias is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        value = session.get(EntityValue, alias.entity_value_id)
        entity_type_id = value.entity_type_id
        session.delete(alias)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="entity_update",
            entity_type="entity_alias",
            entity_id=alias_id,
            payload={"deleted": True},
        )

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/entity-aliases/{alias_id}/toggle")
async def admin_entity_alias_toggle(
    request: Request,
    alias_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        alias = session.get(EntityValueAlias, alias_id)
        if alias is None:
            return RedirectResponse(url="/admin/entities", status_code=status.HTTP_303_SEE_OTHER)
        value = session.get(EntityValue, alias.entity_value_id)
        entity_type_id = value.entity_type_id
        alias.enabled = not alias.enabled
        session.add(alias)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="entity_update",
            entity_type="entity_alias",
            entity_id=alias_id,
            payload={"enabled": alias.enabled},
        )

    return _redirect_to_admin_entity(entity_type_id)


@router.post("/admin/examples/{example_id}/update")
async def admin_example_update(
    request: Request,
    example_id: int,
    form: ExampleUpdateForm = Depends(ExampleUpdateForm.as_form),
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        example = session.get(CommandExample, example_id)
        if example is None:
            return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)

        phrase = form.phrase.strip()
        if not phrase:
            return _redirect_to_admin_command(example.command_id)

        normalized_phrase = normalize_text(phrase)
        duplicate = session.exec(
            select(CommandExample).where(
                CommandExample.command_id == example.command_id,
                CommandExample.normalized_phrase == normalized_phrase,
                CommandExample.id != example.id,
            )
        ).first()
        if duplicate is None:
            example.phrase = phrase
            example.normalized_phrase = normalized_phrase
            example.language = _normalize_optional_text(form.language)
            example.match_type = _parse_match_type(form.match_type)
            example.enabled = form.enabled
            session.add(example)
            session.commit()
            set_catalog_dirty(session, True)
            _audit_log(
                session,
                actor_user_id=getattr(current_user, "id", None),
                action="command_update",
                entity_type="command_example",
                entity_id=example_id,
                payload={"phrase": phrase, "enabled": example.enabled},
            )

        command_id = example.command_id

    return _redirect_to_admin_command(command_id)


@router.post("/admin/examples/{example_id}/delete")
async def admin_example_delete(
    request: Request,
    example_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        example = session.get(CommandExample, example_id)
        if example is None:
            return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)
        command_id = example.command_id
        session.delete(example)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="example_delete",
            entity_type="command_example",
            entity_id=example_id,
            payload={"command_id": command_id},
        )

    return _redirect_to_admin_command(command_id)


@router.post("/admin/examples/{example_id}/toggle")
async def admin_example_toggle(
    request: Request,
    example_id: int,
    _: None = Depends(require_csrf),
):
    current_user = _require_role(request, UserRole.EDITOR)
    if current_user is None:
        return _redirect_to_login()
    if current_user is False:
        return _forbidden_response()
    if SessionFactory is None or engine is None:
        return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)

    with SessionFactory(engine) as session:
        example = session.get(CommandExample, example_id)
        if example is None:
            return RedirectResponse(url="/admin/commands", status_code=status.HTTP_303_SEE_OTHER)
        example.enabled = not example.enabled
        command_id = example.command_id
        session.add(example)
        session.commit()
        set_catalog_dirty(session, True)
        _audit_log(
            session,
            actor_user_id=getattr(current_user, "id", None),
            action="command_update",
            entity_type="command_example",
            entity_id=example_id,
            payload={"enabled": example.enabled},
        )

    return _redirect_to_admin_command(command_id)
