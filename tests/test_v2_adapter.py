from __future__ import annotations

from app.schemas import CommandName, MatchMethod, NormalizedCommand, NormalizeResponse
from app.v2.adapter import v1_command_to_v2, v1_response_to_v2


def test_v1_select_monitor_converts_monitor_param() -> None:
    command = NormalizedCommand(
        command=CommandName.SELECT_MONITOR,
        confidence=1.0,
        method=MatchMethod.entity_rule,
        monitor=2,
        raw_fragment="monitor 2",
    )

    converted = v1_command_to_v2(command)

    assert converted.code == "SELECT_MONITOR"
    assert converted.type == "core"
    assert converted.client_action_key == "select_monitor"
    assert converted.params == {"monitor": 2}


def test_v1_set_size_converts_size_inches_param() -> None:
    command = NormalizedCommand(
        command=CommandName.SET_SIZE,
        confidence=1.0,
        method=MatchMethod.entity_rule,
        size_inches=75,
        raw_fragment="75 pulgadas",
    )

    converted = v1_command_to_v2(command)

    assert converted.code == "SET_SIZE"
    assert converted.client_action_key == "set_size"
    assert converted.params == {"size_inches": 75}


def test_v1_move_right_has_empty_params() -> None:
    command = NormalizedCommand(
        command=CommandName.MOVE_RIGHT,
        confidence=1.0,
        method=MatchMethod.exact_rule,
        raw_fragment="derecha",
    )

    converted = v1_command_to_v2(command)

    assert converted.code == "MOVE_RIGHT"
    assert converted.params == {}
    assert converted.method == "exact_rule"


def test_v1_response_converts_to_v2_response() -> None:
    response = NormalizeResponse(
        ok=True,
        raw_text="monitor 2 75 pulgadas",
        normalized_text="monitor 2 75 pulgadas",
        language="es",
        commands=[
            NormalizedCommand(
                command=CommandName.SELECT_MONITOR,
                confidence=1.0,
                method=MatchMethod.entity_rule,
                monitor=2,
                raw_fragment="monitor 2",
            ),
            NormalizedCommand(
                command=CommandName.SET_SIZE,
                confidence=1.0,
                method=MatchMethod.entity_rule,
                size_inches=75,
                raw_fragment="75 pulgadas",
            ),
        ],
        needs_confirmation=False,
    )

    converted = v1_response_to_v2(response)

    assert converted.ok is True
    assert converted.raw_text == response.raw_text
    assert converted.commands[0].params == {"monitor": 2}
    assert converted.commands[1].params == {"size_inches": 75}
    assert converted.needs_confirmation is False
