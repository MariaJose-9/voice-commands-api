from __future__ import annotations

from app.schemas import CommandName, MatchMethod, NormalizedCommand
from app.v2.schemas import DynamicCommand, NormalizeV2Response


def test_dynamic_command_accepts_custom_code() -> None:
    command = DynamicCommand(
        code="ROTATE_SCREEN",
        type="custom",
        client_action_key="rotate_screen",
        confidence=0.91,
        method="llm",
        params={"monitor": 2, "angle": 90},
        raw_fragment="rota el monitor dos noventa grados",
    )

    assert command.code == "ROTATE_SCREEN"
    assert command.type == "custom"
    assert command.params["angle"] == 90


def test_dynamic_command_accepts_core_set_size() -> None:
    command = DynamicCommand(
        code="SET_SIZE",
        type="core",
        client_action_key="set_size",
        confidence=1.0,
        method="entity_rule",
        params={"size_inches": 75},
        raw_fragment="75 pulgadas",
    )

    assert command.code == "SET_SIZE"
    assert command.type == "core"
    assert command.params == {"size_inches": 75}


def test_normalize_v2_response_serializes() -> None:
    response = NormalizeV2Response(
        ok=True,
        raw_text="rota pantalla dos a 90 grados",
        normalized_text="rota pantalla dos a 90 grados",
        language="es",
        commands=[
            DynamicCommand(
                code="ROTATE_SCREEN",
                type="custom",
                client_action_key="rotate_screen",
                confidence=0.88,
                method="llm",
                params={"monitor": 2, "angle": 90},
            )
        ],
        needs_confirmation=False,
    )

    payload = response.model_dump(mode="json")

    assert payload["ok"] is True
    assert payload["commands"][0]["code"] == "ROTATE_SCREEN"
    assert payload["commands"][0]["params"]["monitor"] == 2


def test_v1_normalized_command_still_works() -> None:
    command = NormalizedCommand(
        command=CommandName.SET_SIZE,
        confidence=1.0,
        method=MatchMethod.entity_rule,
        size_inches=75,
        raw_fragment="75 pulgadas",
    )

    assert command.command == CommandName.SET_SIZE
    assert command.size_inches == 75
