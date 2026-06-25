from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
sqlmodel = pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import CommandDefinition, CommandExample
from app.schemas import CommandName
from app.services import catalog_service


@pytest.fixture
def sqlite_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def setup_function() -> None:
    catalog_service.clear_catalog_cache()


def test_get_active_catalog_returns_mysql_data(sqlite_session: Session) -> None:
    sqlite_session.add(
        CommandDefinition(
            code=CommandName.START_STREAM,
            display_name="Start Stream",
            description="Start a live stream",
            category="Capture / Stream",
            enabled=True,
            priority=80,
        )
    )
    sqlite_session.commit()
    command = sqlite_session.get(CommandDefinition, 1)
    sqlite_session.add_all(
        [
            CommandExample(
                command_id=command.id,
                phrase="start stream",
                normalized_phrase="start stream",
                enabled=True,
            ),
            CommandExample(
                command_id=command.id,
                phrase="iniciar stream",
                normalized_phrase="iniciar stream",
                enabled=True,
            ),
        ]
    )
    sqlite_session.commit()

    result = catalog_service.get_active_catalog(session=sqlite_session)

    assert result == [
        {
            "command": "START_STREAM",
            "description": "Start a live stream",
            "category": "Capture / Stream",
            "priority": 80,
            "requires_entities": [],
            "examples": ["iniciar stream", "start stream"],
        }
    ]
    metadata = catalog_service.get_catalog_metadata()
    assert metadata["source"] == "mysql"
    assert metadata["command_count"] == 1
    assert metadata["example_count"] == 2
    assert metadata["cached"] is True


def test_get_active_catalog_uses_yaml_fallback_when_db_is_empty(
    sqlite_session: Session,
) -> None:
    result = catalog_service.get_active_catalog(session=sqlite_session)

    assert result
    assert any(item["command"] == "SELECT_MONITOR" for item in result)
    metadata = catalog_service.get_catalog_metadata()
    assert metadata["source"] == "yaml_fallback"
    assert metadata["cached"] is True


def test_clear_catalog_cache_resets_cache(sqlite_session: Session) -> None:
    catalog_service.get_active_catalog(session=sqlite_session)
    assert catalog_service.get_catalog_metadata()["cached"] is True

    catalog_service.clear_catalog_cache()

    metadata = catalog_service.get_catalog_metadata()
    assert metadata == {
        "source": "yaml_fallback",
        "command_count": 0,
        "example_count": 0,
        "cached": False,
    }


def test_get_active_catalog_returns_cached_copy(sqlite_session: Session) -> None:
    first = catalog_service.get_active_catalog(session=sqlite_session)
    first.append({"command": "BROKEN"})

    second = catalog_service.get_active_catalog(session=sqlite_session)

    assert all(item.get("command") != "BROKEN" for item in second)


def test_export_catalog_to_yaml_shape(sqlite_session: Session) -> None:
    sqlite_session.add(
        CommandDefinition(
            code=CommandName.SET_LAYOUT,
            display_name="Set Layout",
            description="Apply a layout",
            category="Layouts",
            enabled=True,
            priority=60,
        )
    )
    sqlite_session.commit()
    command = sqlite_session.get(CommandDefinition, 1)
    sqlite_session.add(
        CommandExample(
            command_id=command.id,
            phrase="layout one",
            normalized_phrase="layout one",
            enabled=True,
        )
    )
    sqlite_session.commit()

    payload = catalog_service.export_catalog_to_yaml_shape(sqlite_session)

    assert "commands" in payload
    assert payload["commands"][0]["command"] == "SET_LAYOUT"
    assert payload["commands"][0]["requires_entities"] == ["layout"]
