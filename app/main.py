from __future__ import annotations

import logging
import secrets
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.admin.router import router as admin_router
from app.audio.router import router as audio_router
from app.config import (
    ALLOWED_ORIGINS,
    API_AUTH_TOKEN,
    ENABLE_SEMANTIC_MATCHER,
    ENV,
    MAX_TEXT_LENGTH,
    StructuredLogFormatter,
)
from app.normalizer import normalize_command_text
from app.schemas import NormalizeRequest, NormalizeResponse
from app.semantic_matcher import warmup_semantic_matcher
from app.services.cache_service import rebuild_runtime_indexes
from app.services.catalog_service import get_active_catalog, get_catalog_metadata
from app.services.debug_service import build_debug_response
from app.services.normalization_log_service import save_normalization_log
from app.v2.router import router as commands_v2_router


logger = logging.getLogger(__name__)


def _configure_logging() -> None:
    """Set a minimal structured logging configuration."""

    root_logger = logging.getLogger()
    if root_logger.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(StructuredLogFormatter())
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)


_configure_logging()

app = FastAPI(title="voice-command-api")


def _extract_api_token(request: Request) -> str:
    """Read API token from Authorization Bearer or X-API-Token."""

    authorization = request.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() == "bearer" and token:
        return token.strip()
    return request.headers.get("x-api-token", "").strip()


@app.middleware("http")
async def require_api_token_for_public_api(request: Request, call_next):
    """Protect public API routes when API_AUTH_TOKEN is configured."""

    if ENV == "production" and request.url.path in {
        "/v1/commands/debug",
        "/v1/commands/reload",
        "/v2/commands/debug",
    }:
        return await call_next(request)

    protected_api_path = request.url.path.startswith(("/v1/", "/v2/"))

    if protected_api_path and ENV == "production" and not API_AUTH_TOKEN:
        return JSONResponse(
            status_code=503,
            content={"detail": "API_AUTH_TOKEN must be configured in production."},
        )

    if (API_AUTH_TOKEN or ENV == "production") and protected_api_path:
        token = _extract_api_token(request)
        if not token or not secrets.compare_digest(token, API_AUTH_TOKEN):
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API token."},
                headers={"WWW-Authenticate": "Bearer"},
            )
    return await call_next(request)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials="*" not in ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount(
    "/admin/static",
    StaticFiles(directory=str(Path(__file__).resolve().parent / "admin" / "static")),
    name="admin-static",
)
app.include_router(admin_router)
app.include_router(audio_router)
app.include_router(commands_v2_router)

@lru_cache(maxsize=1)
def _get_examples() -> list[dict[str, Any]]:
    return [
        {
            "request": {
                "text": "monitor two and zoom in",
                "language_hint": "en",
            },
            "response": normalize_command_text(
                "monitor two and zoom in",
                language_hint="en",
            ).model_dump(mode="json"),
        },
        {
            "request": {
                "text": "monitor dos, muevelo a la izquierda y ponlo en 65 pulgadas",
                "language_hint": "es",
            },
            "response": normalize_command_text(
                "monitor dos, muevelo a la izquierda y ponlo en 65 pulgadas",
                language_hint="es",
            ).model_dump(mode="json"),
        },
        {
            "request": {
                "text": "",
                "language_hint": None,
            },
            "response": normalize_command_text("").model_dump(mode="json"),
        },
        {
            "request": {
                "text": "start broadcast maybe",
                "language_hint": "en",
            },
            "response": {
                "ok": True,
                "raw_text": "start broadcast maybe",
                "normalized_text": "start broadcast maybe",
                "language": "en",
                "commands": [
                    {
                        "command": "START_STREAM",
                        "confidence": 0.68,
                        "method": "semantic",
                        "monitor": None,
                        "layout": None,
                        "size_inches": None,
                        "value": None,
                        "raw_fragment": "start broadcast maybe",
                    }
                ],
                "needs_confirmation": True,
                "message": None,
            },
        },
    ]


@app.get("/")
def read_root() -> dict[str, str]:
    return {"message": "voice-command-api"}


@app.get("/health")
def read_health() -> dict[str, str]:
    return {"status": "ok"}


def check_database_health() -> bool:
    """Lazily check database availability."""

    from app.db.session import check_database_connection

    return check_database_connection()


@app.get("/health/db")
def read_health_db():
    try:
        check_database_health()
        return {"status": "ok", "database": "ok"}
    except Exception:
        logger.exception(
            "Database health check failed",
            extra={"event": "health_db_error"},
        )
        return JSONResponse(
            status_code=503,
            content={"status": "error", "database": "unavailable"},
        )


@app.get("/v1/commands/catalog")
def read_catalog() -> dict[str, Any]:
    commands = get_active_catalog()
    metadata = get_catalog_metadata()
    return {
        "source": metadata.get("source", "yaml_fallback"),
        "metadata": metadata,
        "commands": commands,
    }


@app.get("/v1/commands/examples")
def read_examples() -> dict[str, list[dict[str, Any]]]:
    return {"examples": _get_examples()}


@app.post("/v1/commands/normalize", response_model=NormalizeResponse)
def normalize_commands(payload: NormalizeRequest) -> NormalizeResponse:
    try:
        logger.info(
            "normalize request received",
            extra={"event": "normalize_request"},
        )
        response = normalize_command_text(
            text=payload.text,
            language_hint=payload.language_hint,
            context=payload.context,
        )
        try:
            save_normalization_log(
                raw_text=payload.text,
                normalized_text=response.normalized_text,
                language=response.language,
                response=response,
            )
        except Exception:
            logger.warning(
                "Normalization log persistence raised unexpectedly",
                extra={"event": "normalization_log_warning"},
                exc_info=True,
            )
        return response
    except Exception as exc:
        logger.exception(
            "Failed to normalize command text",
            extra={"event": "normalize_error"},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error while normalizing commands.",
        ) from exc


@app.post("/v1/commands/debug")
def debug_commands(payload: NormalizeRequest) -> dict[str, Any]:
    if ENV == "production":
        raise HTTPException(status_code=404, detail="Not Found")

    try:
        return build_debug_response(payload)
    except Exception as exc:
        logger.exception(
            "Failed to build debug command response",
            extra={"event": "debug_error"},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error while building debug response.",
        ) from exc


@app.post("/v1/commands/warmup")
def warmup_commands() -> dict[str, Any]:
    if not ENABLE_SEMANTIC_MATCHER:
        return {
            "enabled": False,
            "message": "Semantic matcher is disabled.",
        }

    try:
        return warmup_semantic_matcher()
    except Exception as exc:
        logger.exception(
            "Failed to warm up semantic matcher",
            extra={"event": "warmup_error"},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error while warming up semantic matcher.",
        ) from exc


@app.post("/v1/commands/reload")
def reload_runtime_commands() -> dict[str, Any]:
    if ENV == "production":
        raise HTTPException(status_code=404, detail="Not Found")

    try:
        return rebuild_runtime_indexes()
    except Exception as exc:
        logger.exception(
            "Failed to rebuild runtime indexes",
            extra={"event": "reload_error"},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error while reloading runtime indexes.",
        ) from exc


@app.post("/admin/dev/seed")
def admin_dev_seed() -> dict[str, Any]:
    if ENV == "production":
        raise HTTPException(status_code=404, detail="Not Found")

    try:
        from app.db.seed import run_seed
        from app.db.session import Session as DBSession, engine

        if DBSession is None or engine is None:
            raise RuntimeError("Database dependencies are not installed.")

        with DBSession(engine) as session:
            return run_seed(session)
    except Exception as exc:
        logger.exception(
            "Failed to run development seed",
            extra={"event": "seed_error"},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error while running development seed.",
        ) from exc


@app.post("/admin/dev/publish-initial-catalog")
def admin_dev_publish_initial_catalog() -> dict[str, Any]:
    if ENV == "production":
        raise HTTPException(status_code=404, detail="Not Found")

    try:
        from app.db.publish_initial_catalog import publish_initial_catalog

        return publish_initial_catalog()
    except Exception as exc:
        logger.exception(
            "Failed to publish initial development catalog",
            extra={"event": "publish_initial_catalog_error"},
        )
        raise HTTPException(
            status_code=500,
            detail="Internal error while publishing initial catalog.",
        ) from exc
