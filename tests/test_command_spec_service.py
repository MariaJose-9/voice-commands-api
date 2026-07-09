from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
sqlmodel = pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db.models import CommandDefinition, CommandExample, CommandParameter, EntityType, utc_now
from app.services import command_spec_service


@pytest.fixture
def sqlite_session(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(command_spec_service, "engine", engine)
    monkeypatch.setattr(command_spec_service, "SessionFactory", Session)
    command_spec_service.clear_command_spec_cache()
    with Session(engine) as session:
        yield session
    command_spec_service.clear_command_spec_cache()


def _add_command(
    session: Session,
    code: str,
    *,
    command_type: str = "core",
    status: str = "active",
    enabled: bool = True,
    deleted: bool = False,
) -> CommandDefinition:
    command = CommandDefinition(
        code=code,
        display_name=code.replace("_", " ").title(),
        description=f"{code} description",
        category="Test",
        command_type=command_type,
        status=status,
        enabled=enabled,
        protected=command_type == "core",
        client_action_key=code.lower(),
        priority=80,
        min_confidence=0.8,
        deleted_at=utc_now() if deleted else None,
    )
    session.add(command)
    session.commit()
    session.refresh(command)
    return command


def _add_entity(session: Session, code: str) -> EntityType:
    entity = EntityType(
        code=code,
        display_name=code.replace("_", " ").title(),
        data_type="integer" if code == "size_inches" else "enum",
        unit="inches" if code == "size_inches" else None,
        dynamic_values=code == "size_inches",
        min_value=40 if code == "size_inches" else None,
        max_value=150 if code == "size_inches" else None,
        protected=code in {"monitor", "layout", "size_inches"},
    )
    session.add(entity)
    session.commit()
    session.refresh(entity)
    return entity


def _add_parameter(
    session: Session,
    command: CommandDefinition,
    entity: EntityType,
    slot_name: str,
    target_field: str,
) -> CommandParameter:
    parameter = CommandParameter(
        command_id=command.id,
        slot_name=slot_name,
        entity_type_id=entity.id,
        target_field=target_field,
        required=True,
        extraction_hint=f"Extract {slot_name}",
    )
    session.add(parameter)
    session.commit()
    session.refresh(parameter)
    return parameter


def test_get_active_command_specs_reads_core_with_parameters(
    sqlite_session: Session,
) -> None:
    command = _add_command(sqlite_session, "SET_SIZE")
    entity = _add_entity(sqlite_session, "size_inches")
    _add_parameter(sqlite_session, command, entity, "size", "size_inches")
    sqlite_session.add(
        CommandExample(
            command_id=command.id,
            phrase="set 75 inches",
            normalized_phrase="set 75 inches",
            enabled=True,
        )
    )
    sqlite_session.commit()

    specs = command_spec_service.get_active_command_specs(force_refresh=True)

    assert len(specs) == 1
    spec = specs[0]
    assert spec.code == "SET_SIZE"
    assert spec.command_type == "core"
    assert spec.examples == ["set 75 inches"]
    assert spec.parameters[0].slot_name == "size"
    assert spec.parameters[0].entity_code == "size_inches"
    assert spec.parameters[0].target_field == "size_inches"
    assert spec.parameters[0].data_type == "integer"
    assert spec.parameters[0].unit == "inches"
    assert spec.parameters[0].dynamic_values is True
    assert spec.parameters[0].min_value == 40
    assert spec.parameters[0].max_value == 150


def test_get_active_command_specs_reads_custom_with_parameters(
    sqlite_session: Session,
) -> None:
    command = _add_command(
        sqlite_session,
        "CUSTOM_ROTATE",
        command_type="custom",
        status="active",
    )
    entity = _add_entity(sqlite_session, "angle_degrees")
    entity.data_type = "integer"
    entity.unit = "degrees"
    entity.dynamic_values = True
    entity.min_value = 0
    entity.max_value = 360
    sqlite_session.add(entity)
    sqlite_session.commit()
    _add_parameter(sqlite_session, command, entity, "angle", "angle")

    spec = command_spec_service.get_command_spec_by_code("CUSTOM_ROTATE")

    assert spec is not None
    assert spec.command_type == "custom"
    assert spec.parameters[0].entity_code == "angle_degrees"
    assert spec.parameters[0].target_field == "angle"
    assert spec.parameters[0].unit == "degrees"


def test_get_active_command_specs_excludes_disabled(sqlite_session: Session) -> None:
    _add_command(sqlite_session, "CUSTOM_DISABLED", status="disabled")

    specs = command_spec_service.get_active_command_specs(force_refresh=True)

    assert all(spec.code != "CUSTOM_DISABLED" for spec in specs)


def test_get_active_command_specs_excludes_deleted_at(sqlite_session: Session) -> None:
    _add_command(sqlite_session, "CUSTOM_DELETED", deleted=True)

    specs = command_spec_service.get_active_command_specs(force_refresh=True)

    assert all(spec.code != "CUSTOM_DELETED" for spec in specs)


def test_clear_command_spec_cache_refreshes_data(sqlite_session: Session) -> None:
    _add_command(sqlite_session, "CUSTOM_FIRST", command_type="custom")
    first = command_spec_service.get_active_command_specs(force_refresh=True)
    assert [spec.code for spec in first] == ["CUSTOM_FIRST"]

    _add_command(sqlite_session, "CUSTOM_SECOND", command_type="custom")
    cached = command_spec_service.get_active_command_specs()
    assert [spec.code for spec in cached] == ["CUSTOM_FIRST"]

    command_spec_service.clear_command_spec_cache()
    refreshed = command_spec_service.get_active_command_specs()

    assert {spec.code for spec in refreshed} == {"CUSTOM_FIRST", "CUSTOM_SECOND"}
