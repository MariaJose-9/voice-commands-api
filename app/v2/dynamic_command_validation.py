from __future__ import annotations

"""Validation helpers for flexible v2 command results."""

from typing import Iterable, Optional

from app.services.command_spec_service import CommandSpec
from app.v2.schemas import DynamicCommand


def _specs_by_code(specs: Iterable[CommandSpec]) -> dict[str, CommandSpec]:
    return {spec.code: spec for spec in specs}


def _coerce_number(value, data_type: str):
    if data_type == "integer":
        return int(value)
    if data_type == "float":
        return float(value)
    return value


def _validate_parameter_value(
    *,
    field_name: str,
    value,
    data_type: str,
    min_value: Optional[float],
    max_value: Optional[float],
) -> None:
    if data_type in {"integer", "float"}:
        try:
            numeric_value = _coerce_number(value, data_type)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Parameter '{field_name}' must be {data_type}.") from exc
        if min_value is not None and numeric_value < min_value:
            raise ValueError(f"Parameter '{field_name}' is below minimum value.")
        if max_value is not None and numeric_value > max_value:
            raise ValueError(f"Parameter '{field_name}' is above maximum value.")
    if data_type == "boolean" and not isinstance(value, bool):
        raise ValueError(f"Parameter '{field_name}' must be boolean.")


def validate_dynamic_command(
    command: DynamicCommand,
    specs: list[CommandSpec],
    client_capabilities: Optional[list[str]] = None,
) -> DynamicCommand:
    """Validate a v2 command against active command specs and client capabilities."""

    spec = _specs_by_code(specs).get(command.code)
    if spec is None:
        raise ValueError(f"Unknown command code: {command.code}")
    if not spec.enabled or spec.status in {"disabled", "deprecated"}:
        raise ValueError(f"Command is not active: {command.code}")
    if command.type != spec.command_type:
        raise ValueError(f"Command type mismatch for {command.code}.")

    client_action_key = command.client_action_key or spec.client_action_key
    if spec.command_type == "custom" and not client_action_key:
        raise ValueError(f"Custom command {command.code} requires client_action_key.")
    if (
        spec.command_type == "custom"
        and client_capabilities is not None
        and client_action_key not in client_capabilities
    ):
        raise ValueError(f"Client does not support action: {client_action_key}")

    for parameter in spec.parameters:
        field_name = parameter.target_field
        if parameter.required and field_name not in command.params:
            raise ValueError(f"Required parameter missing: {field_name}")
        if field_name in command.params:
            _validate_parameter_value(
                field_name=field_name,
                value=command.params[field_name],
                data_type=parameter.data_type,
                min_value=parameter.min_value,
                max_value=parameter.max_value,
            )

    return command.model_copy(update={"client_action_key": client_action_key})
