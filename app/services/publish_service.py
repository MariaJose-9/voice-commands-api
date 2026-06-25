"""Catalog publishing workflow."""

from __future__ import annotations

from typing import Any, Optional

from sqlmodel import select

from app.db.models import (
    AppSetting,
    AuditLog,
    CatalogStatus,
    CatalogVersion,
    EntityType,
    EntityValue,
    EntityValueAlias,
    utc_now,
)
from app.services.cache_service import clear_all_runtime_caches, rebuild_runtime_indexes
from app.services.catalog_service import get_active_catalog
from app.services.entity_catalog_service import get_active_entities
from app.services.settings_service import set_catalog_dirty


def get_active_version(session) -> Optional[CatalogVersion]:
    """Return the current active catalog version, if any."""

    return session.exec(
        select(CatalogVersion)
        .where(CatalogVersion.status == CatalogStatus.ACTIVE)
        .order_by(CatalogVersion.version_number.desc())
    ).first()


def get_next_version_number(session) -> int:
    """Return the next monotonic catalog version number."""

    latest = session.exec(
        select(CatalogVersion).order_by(CatalogVersion.version_number.desc())
    ).first()
    if latest is None or latest.version_number is None:
        return 1
    return int(latest.version_number) + 1


def _build_settings_snapshot(session) -> dict[str, str]:
    """Return persisted application settings as a simple key/value mapping."""

    settings = session.exec(select(AppSetting).order_by(AppSetting.key)).all()
    return {item.key: item.value for item in settings}


def _build_entities_snapshot(session) -> dict[str, dict[str, list[str]]]:
    """Return active entities from the current DB session, with fallback defaults."""

    entity_types = session.exec(
        select(EntityType)
        .where(EntityType.enabled.is_(True))
        .order_by(EntityType.code)
    ).all()
    if not entity_types:
        return get_active_entities(force_refresh=True)

    type_by_id = {item.id: item for item in entity_types if item.id is not None}
    values = session.exec(
        select(EntityValue)
        .where(EntityValue.enabled.is_(True))
        .order_by(EntityValue.entity_type_id, EntityValue.value)
    ).all()
    values = [item for item in values if item.entity_type_id in type_by_id]
    if not values:
        return get_active_entities(force_refresh=True)

    aliases = session.exec(
        select(EntityValueAlias)
        .where(EntityValueAlias.enabled.is_(True))
        .order_by(EntityValueAlias.entity_value_id, EntityValueAlias.normalized_phrase)
    ).all()

    values_by_id = {item.id: item for item in values if item.id is not None}
    snapshot: dict[str, dict[str, list[str]]] = {}
    for value in values:
        entity_type = type_by_id[value.entity_type_id]
        snapshot.setdefault(entity_type.code, {})
        snapshot[entity_type.code].setdefault(str(value.value), [])

    for alias in aliases:
        value = values_by_id.get(alias.entity_value_id)
        if value is None:
            continue
        entity_type = type_by_id.get(value.entity_type_id)
        if entity_type is None:
            continue
        snapshot.setdefault(entity_type.code, {})
        snapshot[entity_type.code].setdefault(str(value.value), [])
        phrase = alias.normalized_phrase or alias.phrase
        if phrase not in snapshot[entity_type.code][str(value.value)]:
            snapshot[entity_type.code][str(value.value)].append(phrase)

    for entity_code, values_map in snapshot.items():
        for key, phrases in values_map.items():
            values_map[key] = sorted(phrases, key=lambda item: (-len(item), item))

    return snapshot if snapshot else get_active_entities(force_refresh=True)


def build_catalog_snapshot(session) -> dict[str, Any]:
    """Build the full runtime snapshot that becomes a published catalog version."""

    version_number = get_next_version_number(session)
    published_at = utc_now().isoformat()
    commands = get_active_catalog(session=session, force_refresh=True)
    entities = _build_entities_snapshot(session)
    settings = _build_settings_snapshot(session)

    return {
        "commands": commands,
        "entities": entities,
        "settings": settings,
        "published_at": published_at,
        "version_number": version_number,
    }


def publish_catalog(session, actor_user_id: Optional[int] = None) -> dict[str, Any]:
    """Publish the current editable catalog and rebuild runtime indexes."""

    snapshot = build_catalog_snapshot(session)
    version_number = int(snapshot["version_number"])

    active_versions = session.exec(
        select(CatalogVersion).where(CatalogVersion.status == CatalogStatus.ACTIVE)
    ).all()
    for version in active_versions:
        version.status = CatalogStatus.ARCHIVED
        session.add(version)

    published_at = utc_now()
    new_version = CatalogVersion(
        version_number=version_number,
        status=CatalogStatus.ACTIVE,
        snapshot_json=snapshot,
        published_at=published_at,
        created_by=actor_user_id,
    )
    session.add(new_version)
    session.commit()
    session.refresh(new_version)

    set_catalog_dirty(session, False)

    clear_all_runtime_caches()
    rebuild_payload = rebuild_runtime_indexes()

    session.add(
        AuditLog(
            actor_user_id=actor_user_id,
            action="publish_catalog",
            entity_type="catalog_version",
            entity_id=new_version.id,
            payload_json={
                "version_number": version_number,
                "commands": len(snapshot.get("commands", [])),
                "examples": sum(
                    len(item.get("examples", []))
                    for item in snapshot.get("commands", [])
                ),
                "semantic_rebuilt": rebuild_payload.get("semantic_rebuilt", False),
            },
        )
    )
    session.commit()

    commands_count = len(snapshot.get("commands", []))
    examples_count = sum(
        len(item.get("examples", [])) for item in snapshot.get("commands", [])
    )
    return {
        "published": True,
        "version_number": version_number,
        "commands": commands_count,
        "examples": examples_count,
        "semantic_rebuilt": rebuild_payload.get("semantic_rebuilt", False),
    }
