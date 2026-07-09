"""Catalog publishing workflow."""

from __future__ import annotations

import re
from typing import Any, Optional

from sqlmodel import select

from app.db.models import (
    AppSetting,
    AuditLog,
    CatalogStatus,
    CatalogVersion,
    CommandDefinition,
    CommandExample,
    CommandParameter,
    EntityType,
    EntityValue,
    EntityValueAlias,
    utc_now,
)
from app.schemas import CommandName
from app.services.cache_service import clear_all_runtime_caches, rebuild_runtime_indexes
from app.services.catalog_service import get_active_catalog
from app.services.entity_catalog_service import get_active_entities
from app.services.settings_service import set_catalog_dirty

CUSTOM_CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
CLIENT_ACTION_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


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


def _command_code(command: CommandDefinition) -> str:
    return command.code.value if isinstance(command.code, CommandName) else str(command.code)


def _snake_case_from_command_code(code: str) -> str:
    return code.strip().lower()


def _commands_for_publish(session) -> list[CommandDefinition]:
    return session.exec(
        select(CommandDefinition)
        .where(CommandDefinition.enabled.is_(True))
        .where(CommandDefinition.deleted_at.is_(None))
        .where(CommandDefinition.status.notin_(["disabled", "deprecated"]))
        .order_by(CommandDefinition.priority.desc(), CommandDefinition.code)
    ).all()


def _prepare_core_commands_for_publish(session) -> None:
    """Normalize safe metadata defaults for protected core commands."""

    commands = _commands_for_publish(session)
    changed = False
    for command in commands:
        code = _command_code(command)
        if code not in CommandName._value2member_map_:
            continue
        if command.command_type != "core":
            continue
        if not command.protected:
            command.protected = True
            changed = True
        if not command.client_action_key:
            command.client_action_key = _snake_case_from_command_code(code)
            changed = True
        if command.status == "draft":
            command.status = "active"
            changed = True
        if changed:
            session.add(command)
    if changed:
        session.commit()


def validate_catalog_for_publish(session) -> list[dict]:
    """Validate editable command catalog before publishing a runtime version."""

    errors: list[dict] = []
    commands = _commands_for_publish(session)
    core_codes = {command.value for command in CommandName}

    examples = session.exec(
        select(CommandExample).where(CommandExample.enabled.is_(True))
    ).all()
    examples_by_command_id: dict[int, int] = {}
    for example in examples:
        examples_by_command_id[example.command_id] = (
            examples_by_command_id.get(example.command_id, 0) + 1
        )

    parameters = session.exec(
        select(CommandParameter).where(CommandParameter.deleted_at.is_(None))
    ).all()
    parameters_by_command_id: dict[int, list[CommandParameter]] = {}
    for parameter in parameters:
        parameters_by_command_id.setdefault(parameter.command_id, []).append(parameter)

    def add_error(command: CommandDefinition, field: str, message: str) -> None:
        errors.append(
            {
                "command_id": command.id,
                "command": _command_code(command),
                "field": field,
                "message": message,
            }
        )

    for command in commands:
        code = _command_code(command).strip()
        if not code:
            add_error(command, "code", "Command code is required.")
        elif not CUSTOM_CODE_PATTERN.fullmatch(code):
            add_error(command, "code", "Command code must use uppercase snake case.")

        if not command.display_name or not command.display_name.strip():
            add_error(command, "display_name", "Display name is required.")

        if examples_by_command_id.get(command.id or 0, 0) < 1:
            add_error(command, "examples", "At least one enabled example is required.")

        if command.command_type not in {"core", "custom"}:
            add_error(command, "command_type", "Command type must be core or custom.")

        if command.status in {"disabled", "deprecated"}:
            add_error(command, "status", "Disabled or deprecated commands cannot be published.")

        if command.command_type == "custom":
            if not command.client_action_key or not command.client_action_key.strip():
                add_error(command, "client_action_key", "Client action key is required.")
            elif not CLIENT_ACTION_KEY_PATTERN.fullmatch(command.client_action_key):
                add_error(command, "client_action_key", "Client action key must be snake_case.")
            if command.protected:
                add_error(command, "protected", "Custom commands cannot be protected.")
            if code in core_codes:
                add_error(command, "code", "Custom command code collides with a core command.")

        if command.command_type == "core":
            if code not in core_codes:
                add_error(command, "code", "Core command code must exist in CommandName.")
            if not command.protected:
                add_error(command, "protected", "Core commands must be protected.")
            if not command.client_action_key:
                add_error(command, "client_action_key", "Core command client_action_key is required.")

        for parameter in parameters_by_command_id.get(command.id or 0, []):
            if parameter.required:
                entity_type = session.get(EntityType, parameter.entity_type_id)
                if entity_type is None:
                    add_error(
                        command,
                        "parameter.entity_type",
                        f"Required parameter '{parameter.slot_name}' references a missing entity type.",
                    )
                elif not entity_type.enabled or entity_type.deleted_at is not None:
                    add_error(
                        command,
                        "parameter.entity_type",
                        f"Required parameter '{parameter.slot_name}' requires an active entity type.",
                    )
            if not parameter.target_field or not parameter.target_field.strip():
                add_error(
                    command,
                    "parameter.target_field",
                    f"Parameter '{parameter.slot_name}' target_field is required.",
                )

    return errors


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

    _prepare_core_commands_for_publish(session)
    errors = validate_catalog_for_publish(session)
    if errors:
        return {
            "published": False,
            "errors": errors,
        }

    draft_custom_commands = session.exec(
        select(CommandDefinition)
        .where(CommandDefinition.command_type == "custom")
        .where(CommandDefinition.status == "draft")
        .where(CommandDefinition.enabled.is_(True))
        .where(CommandDefinition.deleted_at.is_(None))
    ).all()
    for command in draft_custom_commands:
        command.status = "active"
        session.add(command)
    if draft_custom_commands:
        session.commit()

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
