from __future__ import annotations

import importlib

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.main as main_module
from app.db.models import (
    AppSetting,
    CommandDefinition,
    CommandParameter,
    EntityType,
    UserRole,
)


admin_router_module = importlib.import_module("app.admin.router")


class FakeUser:
    id = 1
    email = "admin@example.com"
    role = UserRole.ADMIN


@pytest.fixture
def client_with_sqlite(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    monkeypatch.setattr(admin_router_module, "SessionFactory", Session)
    monkeypatch.setattr(admin_router_module, "engine", engine)
    monkeypatch.setattr(admin_router_module, "get_current_admin_user", lambda token: FakeUser())

    return TestClient(main_module.app), engine


def test_admin_create_angle_degrees_entity(client_with_sqlite) -> None:
    client, engine = client_with_sqlite

    response = client.post(
        "/admin/entities/new",
        data={
            "code": "angle_degrees",
            "display_name": "Angle Degrees",
            "description": "Rotation angle",
            "data_type": "integer",
            "unit": "degrees",
            "dynamic_values": "on",
            "min_value": "0",
            "max_value": "360",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(engine) as session:
        entity_type = session.exec(
            select(EntityType).where(EntityType.code == "angle_degrees")
        ).first()
        assert entity_type is not None
        assert entity_type.display_name == "Angle Degrees"
        assert entity_type.data_type == "integer"
        assert entity_type.unit == "degrees"
        assert entity_type.dynamic_values is True
        assert entity_type.min_value == 0
        assert entity_type.max_value == 360
        assert entity_type.protected is False
        dirty = session.exec(
            select(AppSetting).where(AppSetting.key == "CATALOG_DIRTY")
        ).first()
        assert dirty is not None
        assert dirty.value == "true"


def test_admin_create_distance_custom_entity(client_with_sqlite) -> None:
    client, engine = client_with_sqlite

    response = client.post(
        "/admin/entities/new",
        data={
            "code": "distance_custom",
            "display_name": "Distance Custom",
            "data_type": "float",
            "unit": "meter",
            "dynamic_values": "on",
        },
        follow_redirects=False,
    )

    assert response.status_code == 303
    with Session(engine) as session:
        entity_type = session.exec(
            select(EntityType).where(EntityType.code == "distance_custom")
        ).first()
        assert entity_type is not None
        assert entity_type.data_type == "float"
        assert entity_type.unit == "meter"
        assert entity_type.dynamic_values is True


def test_admin_blocks_delete_of_protected_entity(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        entity_type = EntityType(
            code="monitor",
            display_name="Monitor",
            data_type="enum",
            protected=True,
        )
        session.add(entity_type)
        session.commit()
        session.refresh(entity_type)
        entity_type_id = entity_type.id

    response = client.post(f"/admin/entities/{entity_type_id}/delete")

    assert response.status_code == 400
    assert "Protected entity types cannot be deleted" in response.text
    with Session(engine) as session:
        entity_type = session.get(EntityType, entity_type_id)
        assert entity_type is not None
        assert entity_type.deleted_at is None
        assert entity_type.enabled is True


def test_admin_blocks_disable_of_entity_used_by_active_command(
    client_with_sqlite,
) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        entity_type = EntityType(
            code="distance_custom",
            display_name="Distance Custom",
            data_type="float",
            enabled=True,
        )
        command = CommandDefinition(
            code="CUSTOM_DISTANCE",
            display_name="Custom Distance",
            command_type="custom",
            status="active",
        )
        session.add(entity_type)
        session.add(command)
        session.commit()
        session.refresh(entity_type)
        session.refresh(command)
        session.add(
            CommandParameter(
                command_id=command.id,
                slot_name="distance",
                entity_type_id=entity_type.id,
                target_field="value",
            )
        )
        session.commit()
        entity_type_id = entity_type.id

    response = client.post(f"/admin/entities/{entity_type_id}/disable")

    assert response.status_code == 400
    assert "used by active command parameters" in response.text
    with Session(engine) as session:
        entity_type = session.get(EntityType, entity_type_id)
        assert entity_type is not None
        assert entity_type.enabled is True


def test_admin_entity_detail_shows_used_by_commands(client_with_sqlite) -> None:
    client, engine = client_with_sqlite
    with Session(engine) as session:
        entity_type = EntityType(
            code="angle_degrees",
            display_name="Angle Degrees",
            data_type="integer",
        )
        command = CommandDefinition(
            code="CUSTOM_ROTATE_SCREEN",
            display_name="Rotate Screen",
            command_type="custom",
            status="active",
        )
        session.add(entity_type)
        session.add(command)
        session.commit()
        session.refresh(entity_type)
        session.refresh(command)
        session.add(
            CommandParameter(
                command_id=command.id,
                slot_name="angle",
                entity_type_id=entity_type.id,
                target_field="angle",
            )
        )
        session.commit()
        entity_type_id = entity_type.id

    response = client.get(f"/admin/entities/{entity_type_id}")

    assert response.status_code == 200
    assert "Used By Commands" in response.text
    assert "CUSTOM_ROTATE_SCREEN" in response.text
    assert "data_type" in response.text
    assert "integer" in response.text
