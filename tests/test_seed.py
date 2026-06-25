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


def test_seed_default_entities(sqlite_session: Session) -> None:
    result = seed_default_entities(sqlite_session)
    assert result["entity_types"] == 3
    assert sqlite_session.exec(select(EntityType)).all()
    assert sqlite_session.exec(select(EntityValue)).all()
    assert sqlite_session.exec(select(EntityValueAlias)).all()


def test_seed_default_settings(sqlite_session: Session) -> None:
    result = seed_default_settings(sqlite_session)
    assert result["settings_created"] > 0
    assert sqlite_session.exec(select(AppSetting)).all()


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
