from __future__ import annotations

import pytest

from app.schemas import CommandName, MatchMethod, NormalizedCommand, NormalizeResponse
from app.services.command_spec_service import CommandParameterSpec, CommandSpec
from app.v2.dynamic_command_validation import validate_dynamic_command
from app.v2.schemas import DynamicCommand
import app.v2.normalizer as v2_normalizer


def _base_v1_response() -> NormalizeResponse:
    return NormalizeResponse(
        ok=True,
        raw_text="monitor 1",
        normalized_text="monitor 1",
        language="es",
        commands=[
            NormalizedCommand(
                command=CommandName.SELECT_MONITOR,
                confidence=1.0,
                method=MatchMethod.entity_rule,
                monitor=1,
                raw_fragment="monitor 1",
            )
        ],
        needs_confirmation=False,
    )


def _rotate_spec() -> CommandSpec:
    return CommandSpec(
        code="ROTATE_SCREEN",
        display_name="Rotate Screen",
        command_type="custom",
        status="active",
        enabled=True,
        protected=False,
        client_action_key="rotate_screen",
        examples=["rota el monitor dos noventa grados"],
        parameters=[
            CommandParameterSpec(
                slot_name="angle",
                entity_code="angle_degrees",
                target_field="angle",
                required=True,
                allow_multiple=False,
                data_type="integer",
                unit="degrees",
                dynamic_values=True,
                min_value=0,
                max_value=360,
            )
        ],
    )


def test_v2_returns_core_from_v1(monkeypatch) -> None:
    monkeypatch.setattr(v2_normalizer, "normalize_command_text", lambda **kwargs: _base_v1_response())
    monkeypatch.setattr(v2_normalizer, "_llm_enabled", lambda: False)
    monkeypatch.setattr(v2_normalizer, "get_active_command_specs", lambda: [])

    response = v2_normalizer.normalize_command_text_v2("monitor 1", language_hint="es")

    assert response.ok is True
    assert response.commands[0].code == "SELECT_MONITOR"
    assert response.commands[0].type == "core"
    assert response.commands[0].params == {"monitor": 1}


def test_v2_accepts_custom_command_when_spec_exists(monkeypatch) -> None:
    custom_command = DynamicCommand(
        code="ROTATE_SCREEN",
        type="custom",
        client_action_key="rotate_screen",
        confidence=0.9,
        method="llm",
        params={"angle": 90},
        raw_fragment="rota noventa grados",
    )
    monkeypatch.setattr(v2_normalizer, "normalize_command_text", lambda **kwargs: _base_v1_response())
    monkeypatch.setattr(v2_normalizer, "_llm_enabled", lambda: True)
    monkeypatch.setattr(v2_normalizer, "get_active_command_specs", lambda: [_rotate_spec()])
    monkeypatch.setattr(
        v2_normalizer,
        "interpret_dynamic_commands_with_llm",
        lambda **kwargs: [custom_command],
    )

    response = v2_normalizer.normalize_command_text_v2(
        "rota pantalla uno",
        client_capabilities=["rotate_screen"],
    )

    assert [command.code for command in response.commands] == [
        "SELECT_MONITOR",
        "ROTATE_SCREEN",
    ]
    assert response.commands[1].params == {"angle": 90}
    assert response.needs_confirmation is False


def test_v2_rejects_custom_command_when_client_lacks_capability(monkeypatch) -> None:
    custom_command = DynamicCommand(
        code="ROTATE_SCREEN",
        type="custom",
        client_action_key="rotate_screen",
        confidence=0.9,
        method="llm",
        params={"angle": 90},
    )
    monkeypatch.setattr(v2_normalizer, "normalize_command_text", lambda **kwargs: _base_v1_response())
    monkeypatch.setattr(v2_normalizer, "_llm_enabled", lambda: True)
    monkeypatch.setattr(v2_normalizer, "get_active_command_specs", lambda: [_rotate_spec()])
    monkeypatch.setattr(
        v2_normalizer,
        "interpret_dynamic_commands_with_llm",
        lambda **kwargs: [custom_command],
    )

    response = v2_normalizer.normalize_command_text_v2(
        "rota pantalla uno",
        client_capabilities=["set_size"],
    )

    assert [command.code for command in response.commands] == ["SELECT_MONITOR"]
    assert response.needs_confirmation is True


def test_validate_dynamic_command_rejects_required_param_missing() -> None:
    command = DynamicCommand(
        code="ROTATE_SCREEN",
        type="custom",
        client_action_key="rotate_screen",
        confidence=0.9,
        method="llm",
        params={},
    )

    with pytest.raises(ValueError, match="Required parameter missing"):
        validate_dynamic_command(command, [_rotate_spec()])


def test_validate_dynamic_command_accepts_angle_90() -> None:
    command = DynamicCommand(
        code="ROTATE_SCREEN",
        type="custom",
        client_action_key="rotate_screen",
        confidence=0.9,
        method="llm",
        params={"angle": 90},
    )

    validated = validate_dynamic_command(command, [_rotate_spec()])

    assert validated.params["angle"] == 90


def test_validate_dynamic_command_rejects_angle_above_max() -> None:
    command = DynamicCommand(
        code="ROTATE_SCREEN",
        type="custom",
        client_action_key="rotate_screen",
        confidence=0.9,
        method="llm",
        params={"angle": 999},
    )

    with pytest.raises(ValueError, match="above maximum"):
        validate_dynamic_command(command, [_rotate_spec()])
