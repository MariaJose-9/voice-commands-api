"""Entity catalog service with MySQL-first and hardcoded fallback behavior."""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.preprocessor import normalize_text

try:
    from sqlalchemy import asc
    from sqlmodel import Session, select
except ImportError:  # pragma: no cover
    Session = None
    select = None
    asc = None
    EntityType = None
    EntityValue = None
    EntityValueAlias = None
    SessionFactory = None
    engine = None
else:  # pragma: no cover
    try:
        from app.db.models import EntityType, EntityValue, EntityValueAlias
        from app.db.session import Session as SessionFactory, engine
    except Exception:
        EntityType = None
        EntityValue = None
        EntityValueAlias = None
        SessionFactory = None
        engine = None


logger = logging.getLogger(__name__)
_ENTITY_CACHE: Optional[dict[str, dict[str, list[str]]]] = None

_FALLBACK_ENTITIES = {
    "monitor": {
        "1": [
            "monitor one",
            "monitor 1",
            "monitor uno",
            "pantalla uno",
            "pantalla una",
            "pantalla 1",
            "la pantalla uno",
            "la pantalla una",
            "monitor numero uno",
            "monitor número uno",
            "pantalla numero uno",
            "pantalla número uno",
            "primera pantalla",
            "la primera pantalla",
            "primer monitor",
            "el primer monitor",
            "first monitor",
            "screen one",
            "screen 1",
            "screen number one",
            "display one",
            "display 1",
            "monito uno",
            "monito 1",
            "monitr one",
            "moniter one",
        ],
        "2": [
            "monitor two",
            "monitor 2",
            "monitor dos",
            "pantalla dos",
            "pantalla 2",
            "la pantalla dos",
            "monitor numero dos",
            "monitor número dos",
            "pantalla numero dos",
            "pantalla número dos",
            "segunda pantalla",
            "la segunda pantalla",
            "segundo monitor",
            "el segundo monitor",
            "second monitor",
            "screen two",
            "screen 2",
            "screen number two",
            "display two",
            "display 2",
            "monito dos",
            "monito 2",
            "monitr two",
            "moniter two",
        ],
    },
    "layout": {
        "1": [
            "layout one",
            "layout 1",
            "layout uno",
            "first layout",
            "primer layout",
            "primer diseño",
            "primer diseno",
            "diseno uno",
            "diseño uno",
            "vista uno",
            "vista 1",
            "primera vista",
        ],
        "2": [
            "layout two",
            "layout 2",
            "layout dos",
            "second layout",
            "segundo layout",
            "segundo diseño",
            "segundo diseno",
            "diseno dos",
            "diseño dos",
            "vista dos",
            "vista 2",
            "segunda vista",
        ],
    },
    "size_inches": {
        value: [
            f"{value} inch",
            f"{value} inches",
            f"{value} pulgadas",
            f"{value} puladas",
            f"tamano {value}",
            f"tamano de {value}",
            f"set {value} inches",
            f"ponlo en {value} pulgadas",
            f"ponlo en {value} puladas",
        ]
        for value in ("55", "65", "75", "95", "120")
    },
}


def clear_entity_catalog_cache() -> None:
    """Clear the in-memory entity catalog cache."""

    global _ENTITY_CACHE
    _ENTITY_CACHE = None


def _normalize_aliases(entities: dict[str, dict[str, list[str]]]) -> dict[str, dict[str, list[str]]]:
    """Return a normalized, deduplicated copy of the entity catalog."""

    normalized: dict[str, dict[str, list[str]]] = {}
    for entity_code, values in entities.items():
        normalized[entity_code] = {}
        for value, aliases in values.items():
            seen: set[str] = set()
            normalized_aliases: list[str] = []
            for alias in aliases:
                normalized_alias = normalize_text(alias)
                if not normalized_alias or normalized_alias in seen:
                    continue
                seen.add(normalized_alias)
                normalized_aliases.append(normalized_alias)
            normalized_aliases.sort(key=lambda item: (-len(item), item))
            normalized[entity_code][str(value)] = normalized_aliases
    return normalized


def _fallback_entities() -> dict[str, dict[str, list[str]]]:
    """Return the default hardcoded entities."""

    return _normalize_aliases(_FALLBACK_ENTITIES)


def _merge_entities(
    base: dict[str, dict[str, list[str]]],
    override: dict[str, dict[str, list[str]]],
) -> dict[str, dict[str, list[str]]]:
    """Merge DB-backed entities over the fallback catalog."""

    merged = {
        entity_type: {value: list(aliases) for value, aliases in values.items()}
        for entity_type, values in base.items()
    }
    for entity_type, values in override.items():
        merged.setdefault(entity_type, {})
        for value, aliases in values.items():
            existing = merged[entity_type].get(value, [])
            combined = sorted(
                set(existing).union(aliases),
                key=lambda item: (-len(item), item),
            )
            merged[entity_type][value] = combined
    return merged


def _load_entities_from_db(session: Session) -> dict[str, dict[str, list[str]]]:
    """Load active entities and aliases from SQLModel rows."""

    if (
        select is None
        or asc is None
        or EntityType is None
        or EntityValue is None
        or EntityValueAlias is None
    ):
        return {}

    entity_types = session.exec(
        select(EntityType)
        .where(EntityType.enabled.is_(True))
        .where(EntityType.code.in_(("monitor", "layout", "size_inches")))
        .order_by(asc(EntityType.code))
    ).all()
    if not entity_types:
        return {}

    type_by_id = {item.id: item for item in entity_types if item.id is not None}
    entity_values = session.exec(
        select(EntityValue)
        .where(EntityValue.enabled.is_(True))
        .order_by(asc(EntityValue.entity_type_id), asc(EntityValue.value))
    ).all()
    active_values = [item for item in entity_values if item.entity_type_id in type_by_id]
    if not active_values:
        return {}

    values_by_id = {item.id: item for item in active_values if item.id is not None}
    aliases = session.exec(
        select(EntityValueAlias)
        .where(EntityValueAlias.enabled.is_(True))
        .order_by(asc(EntityValueAlias.entity_value_id), asc(EntityValueAlias.phrase))
    ).all()

    entities: dict[str, dict[str, list[str]]] = {}
    for value in active_values:
        entity_type = type_by_id[value.entity_type_id]
        entities.setdefault(entity_type.code, {})
        entities[entity_type.code].setdefault(str(value.value), [])

    for alias in aliases:
        entity_value = values_by_id.get(alias.entity_value_id)
        if entity_value is None:
            continue
        entity_type = type_by_id.get(entity_value.entity_type_id)
        if entity_type is None:
            continue
        entities.setdefault(entity_type.code, {})
        entities[entity_type.code].setdefault(str(entity_value.value), []).append(
            alias.normalized_phrase or alias.phrase
        )

    return _normalize_aliases(entities)


def get_active_entities(force_refresh: bool = False) -> dict:
    """Return active entities from MySQL, or hardcoded fallback if unavailable."""

    global _ENTITY_CACHE

    if _ENTITY_CACHE is not None and not force_refresh:
        return {
            entity_type: {value: list(aliases) for value, aliases in values.items()}
            for entity_type, values in _ENTITY_CACHE.items()
        }

    if (
        Session is None
        or select is None
        or SessionFactory is None
        or engine is None
        or EntityType is None
        or EntityValue is None
        or EntityValueAlias is None
    ):
        logger.warning(
            "entity catalog fallback because database dependencies are unavailable",
            extra={"event": "entity_catalog_fallback"},
        )
        _ENTITY_CACHE = _fallback_entities()
        return get_active_entities()

    try:
        with SessionFactory(engine) as session:
            entities = _load_entities_from_db(session)
        if entities:
            _ENTITY_CACHE = _merge_entities(_fallback_entities(), entities)
            return get_active_entities()
        logger.warning(
            "entity catalog fallback because database has no active entities",
            extra={"event": "entity_catalog_fallback"},
        )
    except Exception:
        logger.exception(
            "entity catalog fallback because database entity load failed",
            extra={"event": "entity_catalog_fallback"},
        )

    _ENTITY_CACHE = _fallback_entities()
    return get_active_entities()
