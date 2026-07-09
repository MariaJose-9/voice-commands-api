from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("sqlalchemy")
sqlmodel = pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import (
    AdminUser,
    AppSetting,
    CommandDefinition,
    CommandExample,
    CommandParameter,
    EntityType,
    EntityValue,
    EntityValueAlias,
)
from app.db.seed import (
    run_seed,
    seed_core_command_parameters,
    seed_commands_from_yaml,
    seed_default_admin_user,
    seed_default_entities,
    seed_default_settings,
)


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


def test_seed_commands_from_yaml(sqlite_session: Session) -> None:
    result = seed_commands_from_yaml(sqlite_session)
    assert result["commands_created"] > 0
    assert result["examples_created"] > 0
    command = sqlite_session.exec(
        select(CommandDefinition).where(CommandDefinition.code == "SELECT_MONITOR")
    ).first()
    assert command is not None
    examples = sqlite_session.exec(select(CommandExample)).all()
    assert len(examples) > 0


def test_seed_commands_marks_core_commands_protected(sqlite_session: Session) -> None:
    seed_commands_from_yaml(sqlite_session)

    command = sqlite_session.exec(
        select(CommandDefinition).where(CommandDefinition.code == "SELECT_MONITOR")
    ).first()

    assert command is not None
    assert command.code == "SELECT_MONITOR"
    assert command.command_type == "core"
    assert command.status == "active"
    assert command.protected is True
    assert command.client_action_key == "select_monitor"


def test_command_parameter_links_command_and_entity_type(sqlite_session: Session) -> None:
    command = CommandDefinition(
        code="CUSTOM_SET_DISTANCE",
        display_name="Set Distance",
        command_type="custom",
        status="draft",
    )
    entity_type = EntityType(code="distance", display_name="Distance")
    sqlite_session.add(command)
    sqlite_session.add(entity_type)
    sqlite_session.commit()
    sqlite_session.refresh(command)
    sqlite_session.refresh(entity_type)

    parameter = CommandParameter(
        command_id=command.id,
        slot_name="distance",
        entity_type_id=entity_type.id,
        target_field="value",
        required=True,
    )
    sqlite_session.add(parameter)
    sqlite_session.commit()
    sqlite_session.refresh(parameter)

    assert parameter.id is not None
    assert parameter.command_id == command.id
    assert parameter.entity_type_id == entity_type.id
    assert parameter.target_field == "value"


def test_seed_commands_from_yaml_loads_coverage_pack(sqlite_session: Session) -> None:
    seed_commands_from_yaml(sqlite_session)

    examples = sqlite_session.exec(select(CommandExample)).all()
    phrases = {example.phrase for example in examples}

    assert len(examples) > 350
    assert "hazlo un poco mas grande" in phrases
    assert "pon pantalla 2 en 55" in phrases


def test_seed_commands_from_yaml_is_idempotent(sqlite_session: Session) -> None:
    seed_commands_from_yaml(sqlite_session)
    first_examples = sqlite_session.exec(select(CommandExample)).all()

    seed_commands_from_yaml(sqlite_session)
    second_examples = sqlite_session.exec(select(CommandExample)).all()
    unique_examples = {
        (example.command_id, example.normalized_phrase) for example in second_examples
    }

    assert len(second_examples) == len(first_examples)
    assert len(second_examples) == len(unique_examples)


def test_seed_default_entities(sqlite_session: Session) -> None:
    result = seed_default_entities(sqlite_session)
    assert result["entity_types"] >= 3
    assert len(sqlite_session.exec(select(EntityType)).all()) == 5
    assert sqlite_session.exec(select(EntityValue)).all()
    assert sqlite_session.exec(select(EntityValueAlias)).all()


def test_seed_default_entities_creates_entity_metadata(sqlite_session: Session) -> None:
    seed_default_entities(sqlite_session)

    entities = {
        entity.code: entity for entity in sqlite_session.exec(select(EntityType)).all()
    }

    assert entities["monitor"].data_type == "enum"
    assert entities["monitor"].protected is True
    assert entities["layout"].data_type == "enum"
    assert entities["layout"].protected is True
    assert entities["size_inches"].data_type == "integer"
    assert entities["size_inches"].unit == "inches"
    assert entities["size_inches"].dynamic_values is True
    assert entities["size_inches"].min_value == 40
    assert entities["size_inches"].max_value == 150
    assert entities["angle_degrees"].data_type == "integer"
    assert entities["angle_degrees"].unit == "degrees"
    assert entities["angle_degrees"].dynamic_values is True
    assert entities["angle_degrees"].min_value == 0
    assert entities["angle_degrees"].max_value == 360
    assert entities["distance"].data_type == "float"
    assert entities["distance"].unit == "meter"
    assert entities["distance"].dynamic_values is True


def test_seed_default_entities_loads_coverage_aliases(sqlite_session: Session) -> None:
    seed_default_entities(sqlite_session)

    aliases = sqlite_session.exec(select(EntityValueAlias)).all()
    phrases = {alias.phrase for alias in aliases}

    assert "pantalla una" in phrases
    assert "cincuenta y cinco pulgadas" in phrases


def _get_parameter(
    session: Session,
    command_code: str,
    slot_name: str,
) -> tuple[CommandDefinition, CommandParameter, EntityType]:
    command = session.exec(
        select(CommandDefinition).where(CommandDefinition.code == command_code)
    ).first()
    assert command is not None
    parameter = session.exec(
        select(CommandParameter).where(
            CommandParameter.command_id == command.id,
            CommandParameter.slot_name == slot_name,
        )
    ).first()
    assert parameter is not None
    entity_type = session.get(EntityType, parameter.entity_type_id)
    assert entity_type is not None
    return command, parameter, entity_type


def test_seed_core_command_parameters_creates_select_monitor(
    sqlite_session: Session,
) -> None:
    seed_commands_from_yaml(sqlite_session)
    seed_default_entities(sqlite_session)

    result = seed_core_command_parameters(sqlite_session)
    _, parameter, entity_type = _get_parameter(
        sqlite_session,
        "SELECT_MONITOR",
        "monitor",
    )

    assert result["parameters_created"] > 0
    assert entity_type.code == "monitor"
    assert parameter.target_field == "monitor"
    assert parameter.required is True


def test_seed_core_command_parameters_creates_set_size(sqlite_session: Session) -> None:
    seed_commands_from_yaml(sqlite_session)
    seed_default_entities(sqlite_session)

    seed_core_command_parameters(sqlite_session)
    _, parameter, entity_type = _get_parameter(sqlite_session, "SET_SIZE", "size")

    assert entity_type.code == "size_inches"
    assert parameter.target_field == "size_inches"
    assert parameter.required is True


def test_seed_core_command_parameters_creates_zoom_out_distance(
    sqlite_session: Session,
) -> None:
    seed_commands_from_yaml(sqlite_session)
    seed_default_entities(sqlite_session)

    seed_core_command_parameters(sqlite_session)
    _, parameter, entity_type = _get_parameter(sqlite_session, "ZOOM_OUT", "distance")

    assert entity_type.code == "distance"
    assert parameter.target_field == "value"
    assert parameter.required is False


def test_seed_core_command_parameters_is_idempotent(sqlite_session: Session) -> None:
    seed_commands_from_yaml(sqlite_session)
    seed_default_entities(sqlite_session)

    seed_core_command_parameters(sqlite_session)
    first_count = len(sqlite_session.exec(select(CommandParameter)).all())
    seed_core_command_parameters(sqlite_session)
    second_count = len(sqlite_session.exec(select(CommandParameter)).all())

    assert second_count == first_count


def test_seed_default_settings(sqlite_session: Session) -> None:
    result = seed_default_settings(sqlite_session)
    assert result["settings_created"] > 0
    settings = {
        setting.key: setting.value for setting in sqlite_session.exec(select(AppSetting)).all()
    }
    assert settings["ENABLE_SEMANTIC_MATCHER"] == "true"
    assert settings["ENABLE_OLLAMA_FALLBACK"] == "true"
    assert settings["FUZZY_THRESHOLD"] == "86"
    assert settings["TRANSCRIPTION_MODEL_NAME"] == "base"
    assert settings["LLM_COMMAND_MODE"] == "hybrid"
    assert settings["OLLAMA_MODEL"] == "qwen2.5:3b"
    assert settings["OLLAMA_TIMEOUT_SECONDS"] == "8"
    assert settings["LLM_ACCEPT_THRESHOLD"] == "0.78"
    assert settings["LLM_CONFIDENCE_CAP"] == "0.90"
    assert settings["ALLOW_DYNAMIC_SIZE_INCHES"] == "true"
    assert settings["MIN_SIZE_INCHES"] == "40"
    assert settings["MAX_SIZE_INCHES"] == "150"


def test_seed_default_settings_does_not_overwrite_existing(sqlite_session: Session) -> None:
    sqlite_session.add(AppSetting(key="FUZZY_THRESHOLD", value="91"))
    sqlite_session.commit()

    seed_default_settings(sqlite_session)

    setting = sqlite_session.exec(
        select(AppSetting).where(AppSetting.key == "FUZZY_THRESHOLD")
    ).first()
    assert setting is not None
    assert setting.value == "91"


def test_seed_default_admin_user(sqlite_session: Session) -> None:
    result = seed_default_admin_user(sqlite_session)
    assert result["admin_created"] is True
    user = sqlite_session.exec(select(AdminUser)).first()
    assert user is not None
    assert user.password_hash != "admin123"


def test_run_seed(sqlite_session: Session) -> None:
    result = run_seed(sqlite_session)
    assert "commands" in result
    assert "entities" in result
    assert "settings" in result
    assert "admin" in result
