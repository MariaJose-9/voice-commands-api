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
    EntityType,
    EntityValue,
    EntityValueAlias,
)
from app.db.seed import (
    run_seed,
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
    assert result["entity_types"] == 3
    assert sqlite_session.exec(select(EntityType)).all()
    assert sqlite_session.exec(select(EntityValue)).all()
    assert sqlite_session.exec(select(EntityValueAlias)).all()


def test_seed_default_entities_loads_coverage_aliases(sqlite_session: Session) -> None:
    seed_default_entities(sqlite_session)

    aliases = sqlite_session.exec(select(EntityValueAlias)).all()
    phrases = {alias.phrase for alias in aliases}

    assert "pantalla una" in phrases
    assert "cincuenta y cinco pulgadas" in phrases


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
