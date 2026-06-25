"""Catalog loading service with MySQL-first and YAML fallback behavior."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml

from app.schemas import CommandName

try:
    from sqlalchemy import desc
    from sqlmodel import Session, select
except ImportError:  # pragma: no cover
    Session = None
    select = None
    desc = None
    CommandDefinition = None
    CommandExample = None
    SessionFactory = None
    engine = None
else:  # pragma: no cover
    try:
        from app.db.models import CommandDefinition, CommandExample
        from app.db.session import Session as SessionFactory, engine
    except Exception:
        CommandDefinition = None
        CommandExample = None
        SessionFactory = None
        engine = None


logger = logging.getLogger(__name__)
CATALOG_YAML_PATH = Path(__file__).resolve().parent.parent / "commands" / "catalog.yml"
_CATALOG_CACHE: Optional[list[dict[str, Any]]] = None
_CATALOG_METADATA = {
    "source": "yaml_fallback",
    "command_count": 0,
    "example_count": 0,
    "cached": False,
}


def clear_catalog_cache() -> None:
    """Clear the in-memory catalog cache and metadata."""

    global _CATALOG_CACHE, _CATALOG_METADATA
    _CATALOG_CACHE = None
    _CATALOG_METADATA = {
        "source": "yaml_fallback",
        "command_count": 0,
        "example_count": 0,
        "cached": False,
    }


def _requires_entities_for_command(command: str) -> list[str]:
    """Infer required entities for commands backed by structured values."""

    if command == CommandName.SELECT_MONITOR.value:
        return ["monitor"]
    if command == CommandName.SET_LAYOUT.value:
        return ["layout"]
    if command == CommandName.SET_SIZE.value:
        return ["size_inches"]
    return []


def _clone_catalog(catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a detached copy of cached catalog rows."""

    return [
        {
            **item,
            "requires_entities": list(item.get("requires_entities", [])),
            "examples": list(item.get("examples", [])),
        }
        for item in catalog
    ]


def _set_cache(source: str, catalog: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Store catalog and derived metadata in memory."""

    global _CATALOG_CACHE, _CATALOG_METADATA
    _CATALOG_CACHE = _clone_catalog(catalog)
    _CATALOG_METADATA = {
        "source": source,
        "command_count": len(catalog),
        "example_count": sum(len(item.get("examples", [])) for item in catalog),
        "cached": True,
    }
    return _clone_catalog(_CATALOG_CACHE)


def _load_yaml_fallback() -> list[dict[str, Any]]:
    """Load the legacy YAML catalog shape."""

    data = yaml.safe_load(CATALOG_YAML_PATH.read_text(encoding="utf-8")) or {}
    commands = data.get("commands", [])
    return [
        {
            "command": item["command"],
            "description": item.get("description"),
            "category": item.get("category"),
            "priority": item.get("priority", 50),
            "requires_entities": list(item.get("requires_entities", [])),
            "examples": sorted(item.get("examples", [])),
        }
        for item in commands
    ]


def _build_catalog_from_db(session: Session) -> list[dict[str, Any]]:
    """Build the catalog shape from SQLModel rows."""

    if (
        select is None
        or desc is None
        or CommandDefinition is None
        or CommandExample is None
    ):
        return []

    command_rows = session.exec(
        select(CommandDefinition)
        .where(CommandDefinition.enabled.is_(True))
        .order_by(desc(CommandDefinition.priority), CommandDefinition.code)
    ).all()

    if not command_rows:
        return []

    examples = session.exec(
        select(CommandExample)
        .where(CommandExample.enabled.is_(True))
        .order_by(CommandExample.phrase)
    ).all()

    examples_by_command_id: dict[int, list[str]] = {}
    for example in examples:
        examples_by_command_id.setdefault(example.command_id, []).append(example.phrase)

    catalog: list[dict[str, Any]] = []
    for row in command_rows:
        command_value = row.code.value if isinstance(row.code, CommandName) else str(row.code)
        catalog.append(
            {
                "command": command_value,
                "description": row.description,
                "category": row.category,
                "priority": row.priority,
                "requires_entities": _requires_entities_for_command(command_value),
                "examples": sorted(examples_by_command_id.get(row.id or 0, [])),
            }
        )

    return catalog


def export_catalog_to_yaml_shape(session) -> dict:
    """Export the active DB catalog in the legacy YAML-compatible shape."""

    return {"commands": _build_catalog_from_db(session)}


def get_active_catalog(
    session: Optional[Session] = None, force_refresh: bool = False
) -> list[dict]:
    """Return the active catalog from MySQL, or YAML fallback if unavailable."""

    if _CATALOG_CACHE is not None and not force_refresh:
        return _clone_catalog(_CATALOG_CACHE)

    if (
        Session is None
        or select is None
        or SessionFactory is None
        or engine is None
        or CommandDefinition is None
        or CommandExample is None
    ):
        logger.warning(
            "catalog fallback to yaml because database dependencies are unavailable",
            extra={"event": "catalog_yaml_fallback"},
        )
        return _set_cache("yaml_fallback", _load_yaml_fallback())

    owned_session = None
    active_session = session
    try:
        if active_session is None:
            owned_session = SessionFactory(engine)
            active_session = owned_session

        catalog = _build_catalog_from_db(active_session)
        if catalog:
            return _set_cache("mysql", catalog)

        logger.warning(
            "catalog fallback to yaml because database has no active commands",
            extra={"event": "catalog_yaml_fallback"},
        )
    except Exception:
        logger.exception(
            "catalog fallback to yaml because database catalog load failed",
            extra={"event": "catalog_yaml_fallback"},
        )
    finally:
        if owned_session is not None:
            owned_session.close()

    return _set_cache("yaml_fallback", _load_yaml_fallback())


def get_catalog_metadata() -> dict:
    """Return metadata for the current in-memory catalog source."""

    return dict(_CATALOG_METADATA)
