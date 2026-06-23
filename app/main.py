from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.config import (
    ALLOWED_ORIGINS,
    ENABLE_SEMANTIC_MATCHER,
    ENV,
    FUZZY_THRESHOLD,
    MAX_TEXT_LENGTH,
    SEMANTIC_CONFIRMATION_THRESHOLD,
    SEMANTIC_THRESHOLD,
    StructuredLogFormatter,
)
from app.entity_extractor import extract_entities
from app.fuzzy_matcher import get_fuzzy_candidates, match_by_fuzzy
from app.multi_command import split_into_fragments
from app.normalizer import normalize_command_text
from app.preprocessor import normalize_text
from app.rule_matcher import match_by_rules
from app.schemas import NormalizeRequest, NormalizeResponse
from app.semantic_matcher import (
    get_semantic_candidates,
    match_by_semantic,
    warmup_semantic_matcher,
)


logger = logging.getLogger(__name__)
CATALOG_PATH = Path(__file__).resolve().parent / "commands" / "catalog.yml"


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

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials="*" not in ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache(maxsize=1)
def _load_catalog() -> list[dict[str, Any]]:
    data = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8")) or {}
    return data.get("commands", [])


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


@app.get("/v1/commands/catalog")
def read_catalog() -> dict[str, list[dict[str, Any]]]:
    return {"commands": _load_catalog()}


@app.get("/v1/commands/examples")
def read_examples() -> dict[str, list[dict[str, Any]]]:
    return {"examples": _get_examples()}


def _build_debug_response(payload: NormalizeRequest) -> dict[str, Any]:
    """Assemble debug data for the normalization pipeline."""

    normalized_text = normalize_text(payload.text) if payload.text else ""
    fragments = split_into_fragments(normalized_text) if normalized_text else []
    entities_by_fragment = []
    rule_matches = []
    fuzzy_candidates = []
    semantic_candidates = []

    for fragment in fragments:
        entities = extract_entities(fragment)
        rule_match_list = match_by_rules(fragment, entities)
        fuzzy_match = match_by_fuzzy(fragment, threshold=FUZZY_THRESHOLD)
        semantic_match = (
            match_by_semantic(
                fragment,
                threshold=SEMANTIC_THRESHOLD,
                confirmation_threshold=SEMANTIC_CONFIRMATION_THRESHOLD,
            )
            if ENABLE_SEMANTIC_MATCHER
            else None
        )

        entities_by_fragment.append({"fragment": fragment, "entities": entities})
        rule_matches.append(
            {
                "fragment": fragment,
                "matches": [
                    match.model_dump(mode="json") for match in rule_match_list
                ],
            }
        )
        fuzzy_candidates.append(
            {
                "fragment": fragment,
                "candidates": get_fuzzy_candidates(fragment),
                "match": (
                    fuzzy_match.model_dump(mode="json")
                    if fuzzy_match is not None
                    else None
                ),
            }
        )
        semantic_candidates.append(
            {
                "fragment": fragment,
                "candidates": (
                    get_semantic_candidates(fragment) if ENABLE_SEMANTIC_MATCHER else []
                ),
                "match": (
                    semantic_match.model_dump(mode="json")
                    if semantic_match is not None
                    else None
                ),
            }
        )

    final_response = normalize_command_text(
        text=payload.text,
        language_hint=payload.language_hint,
        context=payload.context,
    )
    return {
        "raw_text": payload.text,
        "normalized_text": normalized_text,
        "fragments": fragments,
        "entities_by_fragment": entities_by_fragment,
        "rule_matches": rule_matches,
        "fuzzy_candidates": fuzzy_candidates,
        "semantic_candidates": semantic_candidates,
        "final_response": final_response.model_dump(mode="json"),
    }


@app.post("/v1/commands/normalize", response_model=NormalizeResponse)
def normalize_commands(payload: NormalizeRequest) -> NormalizeResponse:
    try:
        logger.info(
            "normalize request received",
            extra={"event": "normalize_request"},
        )
        return normalize_command_text(
            text=payload.text,
            language_hint=payload.language_hint,
            context=payload.context,
        )
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
        return _build_debug_response(payload)
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
