"""Admin panel routes."""

from __future__ import annotations

from pathlib import Path
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
    CommandUpdateForm,
    EntityAliasCreateForm,
    EntityAliasUpdateForm,
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
    ENABLE_SEMANTIC_MATCHER,
    ENABLE_AUDIO_TRANSCRIPTION,
    ENV,
    ENABLE_OLLAMA_FALLBACK,
    FUZZY_THRESHOLD,
    MAX_TEXT_LENGTH,
    MAX_AUDIO_DURATION_SECONDS,
    MAX_AUDIO_FILE_MB,
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
    EntityType,
    EntityValue,
    EntityValueAlias,
    ExampleSource,
    MatchType,
    NormalizationLog,
    ReviewStatus,
    UserRole,
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


router = APIRouter(tags=["admin"])
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))
MATCHING_SETTINGS = {
    "FUZZY_THRESHOLD",
    "SEMANTIC_THRESHOLD",
    "SEMANTIC_CONFIRMATION_THRESHOLD",
    "ENABLE_SEMANTIC_MATCHER",
    "SEMANTIC_MODEL_NAME",
}
EDITABLE_SETTINGS = {
    "FUZZY_THRESHOLD": FUZZY_THRESHOLD,
    "SEMANTIC_THRESHOLD": SEMANTIC_THRESHOLD,
    "SEMANTIC_CONFIRMATION_THRESHOLD": SEMANTIC_CONFIRMATION_THRESHOLD,
    "ENABLE_SEMANTIC_MATCHER": ENABLE_SEMANTIC_MATCHER,
    "ENABLE_OLLAMA_FALLBACK": ENABLE_OLLAMA_FALLBACK,
    "SEMANTIC_MODEL_NAME": SEMANTIC_MODEL_NAME,
    "MAX_TEXT_LENGTH": MAX_TEXT_LENGTH,
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


def _parse_match_type(value: str) -> MatchType:
    return MatchType(value)


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
        dirty = is_catalog_dirty(session)

    return {
        "command": command,
        "examples": examples,
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
        dirty = is_catalog_dirty(session)

    return {
        "entity_type": entity_type,
        "values": values,
        "aliases_by_value": aliases_by_value,
        "catalog_dirty": dirty,
    }


def _load_settings_context() -> dict[str, Any]:
    settings: dict[str, Any] = {}
    if SessionFactory is not None and engine is not None:
        with SessionFactory(engine) as session:
            for key, default in EDITABLE_SETTINGS.items():
                if key in AUDIO_LIST_SETTINGS:
                    settings[key] = ", ".join(get_audio_list_setting(key, default))
                else:
                    settings[key] = get_runtime_setting(key, default)
            dirty = is_catalog_dirty(session)
        return {"settings": settings, "catalog_dirty": dirty}

    return {
        "settings": {
            key: ", ".join(value) if key in AUDIO_LIST_SETTINGS else value
            for key, value in EDITABLE_SETTINGS.items()
        },
        "catalog_dirty": False,
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
        "text": "",
        "language_hint": "",
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
        publish_catalog(session, actor_user_id=getattr(current_user, "id", None))

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
            types = session.exec(select(EntityType).order_by(EntityType.code)).all()
            values = session.exec(select(EntityValue)).all()
            value_counts: dict[int, int] = {}
            for value in values:
                value_counts[value.entity_type_id] = value_counts.get(value.entity_type_id, 0) + 1
            entity_types = [
                {"entity_type": item, "value_count": value_counts.get(item.id or 0, 0)}
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

    with SessionFactory(engine) as session:
        dirty_changed = False
        changed_keys: list[str] = []
        changed_audio_keys: list[str] = []
        audio_model_reload_required = False
        for key, default in EDITABLE_SETTINGS.items():
            raw_value = form.get(key)
            if isinstance(default, bool):
                new_value = "true" if raw_value in {"true", "on", "1", "yes"} else "false"
            elif isinstance(default, list):
                new_value = ", ".join(
                    [item.strip() for item in str(raw_value or "").split(",") if item.strip()]
                ) if raw_value is not None else ", ".join(default)
            elif raw_value is None:
                new_value = str(default)
            else:
                new_value = str(raw_value).strip()

            setting = session.exec(select(AppSetting).where(AppSetting.key == key)).first()
            previous_value = (
                setting.value
                if setting is not None
                else (", ".join(default) if isinstance(default, list) else str(default))
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
    payload = NormalizeRequest(text=text, language_hint=language_hint, context=None)

    context = _load_tester_context()
    context.update(
        {
            "current_user": current_user,
            "text": text,
            "language_hint": language_hint or "",
            "debug_data": build_debug_response(payload),
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
