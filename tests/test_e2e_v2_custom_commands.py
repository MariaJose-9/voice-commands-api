from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.main as main_module
import app.services.command_spec_service as command_spec_service
import app.v2.normalizer as v2_normalizer_module
from app.db.models import CommandDefinition, CommandExample, CommandParameter, EntityType
from app.preprocessor import normalize_text
from app.schemas import CommandName


client = TestClient(main_module.app)
v2_router_module = importlib.import_module("app.v2.router")


@pytest.fixture
def custom_command_engine(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(command_spec_service, "SessionFactory", Session)
    monkeypatch.setattr(command_spec_service, "engine", engine)
    command_spec_service.clear_command_spec_cache()
    monkeypatch.setattr(v2_normalizer_module, "_llm_enabled", lambda: False)

    with Session(engine) as session:
        monitor_type = EntityType(
            code="monitor",
            display_name="Monitor",
            data_type="integer",
            enabled=True,
        )
        angle_type = EntityType(
            code="angle_degrees",
            display_name="Angle Degrees",
            data_type="integer",
            unit="degrees",
            dynamic_values=True,
            min_value=0,
            max_value=360,
            enabled=True,
        )
        command = CommandDefinition(
            code="ROTATE_SCREEN",
            display_name="Rotate Screen",
            command_type="custom",
            status="active",
            enabled=True,
            client_action_key="rotate_screen",
        )
        disabled_command = CommandDefinition(
            code="DISABLED_CUSTOM",
            display_name="Disabled Custom",
            command_type="custom",
            status="disabled",
            enabled=False,
            client_action_key="disabled_custom",
        )
        session.add(monitor_type)
        session.add(angle_type)
        session.add(command)
        session.add(disabled_command)
        session.commit()
        session.refresh(monitor_type)
        session.refresh(angle_type)
        session.refresh(command)
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="rota el monitor 2 noventa grados",
                normalized_phrase=normalize_text("rota el monitor 2 noventa grados"),
                enabled=True,
            )
        )
        session.add(
            CommandExample(
                command_id=command.id,
                phrase="gira pantalla dos 90 grados",
                normalized_phrase=normalize_text("gira pantalla dos 90 grados"),
                enabled=True,
            )
        )
        session.add(
            CommandParameter(
                command_id=command.id,
                slot_name="monitor",
                entity_type_id=monitor_type.id,
                target_field="monitor",
                required=False,
            )
        )
        session.add(
            CommandParameter(
                command_id=command.id,
                slot_name="angle",
                entity_type_id=angle_type.id,
                target_field="angle",
                required=True,
            )
        )
        session.commit()

    yield engine
    command_spec_service.clear_command_spec_cache()


def test_v2_specs_include_rotate_screen(custom_command_engine) -> None:
    response = client.get("/v2/commands/specs")

    assert response.status_code == 200
    codes = [item["code"] for item in response.json()]
    assert "ROTATE_SCREEN" in codes


def test_v2_normalize_returns_rotate_screen_custom(custom_command_engine) -> None:
    response = client.post(
        "/v2/commands/normalize",
        json={
            "text": "rota el monitor 2 noventa grados",
            "language_hint": "es",
            "client_capabilities": ["rotate_screen"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    custom_commands = [
        command for command in payload["commands"] if command["code"] == "ROTATE_SCREEN"
    ]
    assert custom_commands
    command = custom_commands[0]
    assert command["type"] == "custom"
    assert command["client_action_key"] == "rotate_screen"
    assert command["params"]["monitor"] == 2
    assert command["params"]["angle"] == 90


def test_v2_normalize_without_client_capability_marks_confirmation(
    custom_command_engine,
) -> None:
    response = client.post(
        "/v2/commands/normalize",
        json={
            "text": "rota el monitor 2 noventa grados",
            "language_hint": "es",
            "client_capabilities": [],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert all(command["code"] != "ROTATE_SCREEN" for command in payload["commands"])
    assert payload["needs_confirmation"] is True
    assert "Client does not support action" in payload["message"]


def test_v2_normalize_missing_required_angle_marks_confirmation(
    custom_command_engine,
) -> None:
    response = client.post(
        "/v2/commands/normalize",
        json={
            "text": "rota el monitor 2",
            "language_hint": "es",
            "client_capabilities": ["rotate_screen"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert all(command["code"] != "ROTATE_SCREEN" for command in payload["commands"])
    assert payload["needs_confirmation"] is True
    assert "Required parameter missing: angle" in payload["message"]


def test_v1_normalize_does_not_return_custom_command(custom_command_engine) -> None:
    response = client.post(
        "/v1/commands/normalize",
        json={
            "text": "rota el monitor 2 noventa grados",
            "language_hint": "es",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert all(command["command"] != "ROTATE_SCREEN" for command in payload["commands"])
    assert any(
        command["command"] == CommandName.SELECT_MONITOR.value
        for command in payload["commands"]
    )


def test_v2_specs_exclude_disabled_custom(custom_command_engine) -> None:
    response = client.get("/v2/commands/specs")

    assert response.status_code == 200
    codes = [item["code"] for item in response.json()]
    assert "DISABLED_CUSTOM" not in codes
