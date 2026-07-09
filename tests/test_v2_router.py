from __future__ import annotations

from fastapi.testclient import TestClient

import app.main as main_module
import app.v2.router as v2_router
from app.services.command_spec_service import CommandParameterSpec, CommandSpec
from app.schemas import CommandName


client = TestClient(main_module.app)


def _custom_rotate_spec() -> CommandSpec:
    return CommandSpec(
        code="ROTATE_SCREEN",
        display_name="Rotate Screen",
        description="Rotate selected screen.",
        category="Custom",
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


def test_v2_normalize_works_with_core_command() -> None:
    response = client.post(
        "/v2/commands/normalize",
        json={"text": "monitor 1", "language_hint": "es"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["commands"][0]["code"] == "SELECT_MONITOR"
    assert payload["commands"][0]["type"] == "core"
    assert payload["commands"][0]["params"] == {"monitor": 1}


def test_v2_specs_lists_commands(monkeypatch) -> None:
    monkeypatch.setattr(
        v2_router,
        "get_active_command_specs",
        lambda: [
            CommandSpec(
                code="SELECT_MONITOR",
                display_name="Select Monitor",
                command_type="core",
                status="active",
                enabled=True,
                protected=True,
                client_action_key="select_monitor",
            )
        ],
    )

    response = client.get("/v2/commands/specs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["code"] == "SELECT_MONITOR"
    assert payload[0]["type"] == "core"


def test_v2_specs_includes_active_custom(monkeypatch) -> None:
    monkeypatch.setattr(
        v2_router,
        "get_active_command_specs",
        lambda: [_custom_rotate_spec()],
    )

    response = client.get("/v2/commands/specs")

    assert response.status_code == 200
    payload = response.json()
    assert payload[0]["code"] == "ROTATE_SCREEN"
    assert payload[0]["type"] == "custom"
    assert payload[0]["client_action_key"] == "rotate_screen"
    assert payload[0]["parameters"][0]["target_field"] == "angle"


def test_v2_requires_api_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "API_AUTH_TOKEN", "secret-token")

    response = client.get("/v2/commands/specs")

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid or missing API token."}


def test_v2_accepts_api_token_when_configured(monkeypatch) -> None:
    monkeypatch.setattr(main_module, "API_AUTH_TOKEN", "secret-token")
    monkeypatch.setattr(
        v2_router,
        "get_active_command_specs",
        lambda: [_custom_rotate_spec()],
    )

    response = client.get(
        "/v2/commands/specs",
        headers={"Authorization": "Bearer secret-token"},
    )

    assert response.status_code == 200
    assert response.json()[0]["code"] == "ROTATE_SCREEN"


def test_v1_still_works_after_mounting_v2() -> None:
    response = client.post(
        "/v1/commands/normalize",
        json={"text": "left", "language_hint": "en"},
    )

    assert response.status_code == 200
    assert response.json()["commands"][0]["command"] == CommandName.MOVE_LEFT.value
