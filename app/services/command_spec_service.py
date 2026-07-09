"""Runtime command specification loading service.

This service centralizes command definitions, examples, and parameter metadata
for future flexible/custom command flows while leaving the stable /v1 schemas
unchanged.
"""

from __future__ import annotations

import logging
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.services.catalog_service import get_active_catalog

try:
    from sqlalchemy import desc
    from sqlmodel import Session, select
except ImportError:  # pragma: no cover
    Session = None
    select = None
    desc = None
    CommandDefinition = None
    CommandExample = None
    CommandParameter = None
    EntityType = None
    SessionFactory = None
    engine = None
else:  # pragma: no cover
    try:
        from app.db.models import (
            CommandDefinition,
            CommandExample,
            CommandParameter,
            EntityType,
        )
        from app.db.session import Session as SessionFactory, engine
    except Exception:
        CommandDefinition = None
        CommandExample = None
        CommandParameter = None
        EntityType = None
        SessionFactory = None
        engine = None


logger = logging.getLogger(__name__)
_COMMAND_SPEC_CACHE: Optional[list["CommandSpec"]] = None


class CommandParameterSpec(BaseModel):
    """Resolved parameter metadata for a command."""

    model_config = ConfigDict(frozen=True)

    slot_name: str
    entity_code: str
    target_field: str
    required: bool
    allow_multiple: bool
    default_value: Optional[str] = None
    description: Optional[str] = None
    extraction_hint: Optional[str] = None
    data_type: str = "string"
    unit: Optional[str] = None
    dynamic_values: bool = False
    min_value: Optional[float] = None
    max_value: Optional[float] = None


class CommandSpec(BaseModel):
    """Resolved command metadata for runtime/admin usage."""

    model_config = ConfigDict(frozen=True)

    code: str
    display_name: str
    description: Optional[str] = None
    category: Optional[str] = None
    command_type: str = "core"
    status: str = "active"
    enabled: bool = True
    protected: bool = False
    client_action_key: Optional[str] = None
    priority: int = 50
    min_confidence: float = 0.72
    examples: list[str] = []
    parameters: list[CommandParameterSpec] = []


def clear_command_spec_cache() -> None:
    """Clear cached command specs."""

    global _COMMAND_SPEC_CACHE
    _COMMAND_SPEC_CACHE = None


def _clone_specs(specs: list[CommandSpec]) -> list[CommandSpec]:
    """Return detached model copies so callers cannot mutate cache."""

    return [CommandSpec.model_validate(spec.model_dump()) for spec in specs]


def _fallback_specs() -> list[CommandSpec]:
    """Build core specs from the legacy active catalog shape."""

    specs: list[CommandSpec] = []
    for item in get_active_catalog():
        code = str(item.get("command") or "")
        if not code:
            continue
        specs.append(
            CommandSpec(
                code=code,
                display_name=code.replace("_", " ").title(),
                description=item.get("description"),
                category=item.get("category"),
                command_type="core",
                status="active",
                enabled=True,
                protected=True,
                client_action_key=code.lower(),
                priority=int(item.get("priority", 50)),
                min_confidence=0.72,
                examples=sorted(item.get("examples", [])),
                parameters=[],
            )
        )
    return specs


def _build_specs_from_db(session: Session) -> list[CommandSpec]:
    """Build command specs from SQLModel rows."""

    if (
        select is None
        or desc is None
        or CommandDefinition is None
        or CommandExample is None
        or CommandParameter is None
        or EntityType is None
    ):
        return []

    command_rows = session.exec(
        select(CommandDefinition)
        .where(CommandDefinition.enabled.is_(True))
        .where(CommandDefinition.status.notin_(["disabled", "deprecated"]))
        .where(CommandDefinition.deleted_at.is_(None))
        .order_by(desc(CommandDefinition.priority), CommandDefinition.code)
    ).all()
    if not command_rows:
        return []

    command_ids = [row.id for row in command_rows if row.id is not None]
    examples_by_command_id: dict[int, list[str]] = {}
    parameters_by_command_id: dict[int, list[CommandParameterSpec]] = {}

    if command_ids:
        examples = session.exec(
            select(CommandExample)
            .where(CommandExample.enabled.is_(True))
            .where(CommandExample.command_id.in_(command_ids))
            .order_by(CommandExample.phrase)
        ).all()
        for example in examples:
            examples_by_command_id.setdefault(example.command_id, []).append(
                example.phrase
            )

        entity_types = session.exec(select(EntityType)).all()
        entity_by_id = {
            entity.id: entity for entity in entity_types if entity.id is not None
        }

        parameters = session.exec(
            select(CommandParameter)
            .where(CommandParameter.command_id.in_(command_ids))
            .where(CommandParameter.deleted_at.is_(None))
            .order_by(CommandParameter.command_id, CommandParameter.slot_name)
        ).all()
        for parameter in parameters:
            entity_type = entity_by_id.get(parameter.entity_type_id)
            if entity_type is None:
                continue
            parameters_by_command_id.setdefault(parameter.command_id, []).append(
                CommandParameterSpec(
                    slot_name=parameter.slot_name,
                    entity_code=entity_type.code,
                    target_field=parameter.target_field,
                    required=parameter.required,
                    allow_multiple=parameter.allow_multiple,
                    default_value=parameter.default_value,
                    description=parameter.description,
                    extraction_hint=parameter.extraction_hint,
                    data_type=entity_type.data_type,
                    unit=entity_type.unit,
                    dynamic_values=entity_type.dynamic_values,
                    min_value=entity_type.min_value,
                    max_value=entity_type.max_value,
                )
            )

    specs: list[CommandSpec] = []
    for command in command_rows:
        command_id = command.id or 0
        specs.append(
            CommandSpec(
                code=str(command.code),
                display_name=command.display_name,
                description=command.description,
                category=command.category,
                command_type=command.command_type,
                status=command.status,
                enabled=command.enabled,
                protected=command.protected,
                client_action_key=command.client_action_key,
                priority=command.priority,
                min_confidence=command.min_confidence,
                examples=sorted(examples_by_command_id.get(command_id, [])),
                parameters=parameters_by_command_id.get(command_id, []),
            )
        )

    return specs


def get_active_command_specs(force_refresh: bool = False) -> list[CommandSpec]:
    """Return active command specs from DB, with safe core fallback."""

    global _COMMAND_SPEC_CACHE
    if _COMMAND_SPEC_CACHE is not None and not force_refresh:
        return _clone_specs(_COMMAND_SPEC_CACHE)

    if (
        Session is None
        or select is None
        or SessionFactory is None
        or engine is None
        or CommandDefinition is None
        or CommandExample is None
        or CommandParameter is None
        or EntityType is None
    ):
        logger.warning(
            "command spec fallback because database dependencies are unavailable",
            extra={"event": "command_spec_fallback"},
        )
        _COMMAND_SPEC_CACHE = _fallback_specs()
        return _clone_specs(_COMMAND_SPEC_CACHE)

    try:
        with SessionFactory(engine) as session:
            specs = _build_specs_from_db(session)
        if specs:
            _COMMAND_SPEC_CACHE = specs
            return _clone_specs(_COMMAND_SPEC_CACHE)

        logger.warning(
            "command spec fallback because database has no active command specs",
            extra={"event": "command_spec_fallback"},
        )
    except Exception:
        logger.exception(
            "command spec fallback because database command spec load failed",
            extra={"event": "command_spec_fallback"},
        )

    _COMMAND_SPEC_CACHE = _fallback_specs()
    return _clone_specs(_COMMAND_SPEC_CACHE)


def get_command_spec_by_code(code: str) -> Optional[CommandSpec]:
    """Return a command spec by code from the active cached spec list."""

    normalized_code = code.strip()
    if not normalized_code:
        return None
    for spec in get_active_command_specs():
        if spec.code == normalized_code:
            return spec
    return None
