from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

import app.services.runtime_settings_service as runtime_settings_service
from app.db.models import AppSetting


def test_runtime_setting_reads_db_value(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AppSetting(key="FUZZY_THRESHOLD", value="91.5"))
        session.commit()

    monkeypatch.setattr(runtime_settings_service, "SessionFactory", Session)
    monkeypatch.setattr(runtime_settings_service, "engine", engine)

    assert runtime_settings_service.get_float_setting("FUZZY_THRESHOLD", 88.0) == 91.5


def test_runtime_setting_overrides_llm_command_mode(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(AppSetting(key="LLM_COMMAND_MODE", value="primary"))
        session.add(AppSetting(key="ALLOW_DYNAMIC_SIZE_INCHES", value="true"))
        session.add(AppSetting(key="MIN_SIZE_INCHES", value="40"))
        session.add(AppSetting(key="MAX_SIZE_INCHES", value="150"))
        session.commit()

    monkeypatch.setattr(runtime_settings_service, "SessionFactory", Session)
    monkeypatch.setattr(runtime_settings_service, "engine", engine)

    assert (
        runtime_settings_service.get_runtime_str_setting(
            "LLM_COMMAND_MODE",
            "fallback",
        )
        == "primary"
    )
    assert runtime_settings_service.get_runtime_bool_setting(
        "ALLOW_DYNAMIC_SIZE_INCHES",
        False,
    ) is True
    assert runtime_settings_service.get_runtime_int_setting("MIN_SIZE_INCHES", 0) == 40
    assert runtime_settings_service.get_runtime_int_setting("MAX_SIZE_INCHES", 0) == 150


def test_runtime_setting_falls_back_on_db_error(monkeypatch) -> None:
    monkeypatch.setattr(runtime_settings_service, "SessionFactory", None)
    monkeypatch.setattr(runtime_settings_service, "engine", None)

    assert runtime_settings_service.get_float_setting("FUZZY_THRESHOLD", 88.0) == 88.0
