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


def test_runtime_setting_falls_back_on_db_error(monkeypatch) -> None:
    monkeypatch.setattr(runtime_settings_service, "SessionFactory", None)
    monkeypatch.setattr(runtime_settings_service, "engine", None)

    assert runtime_settings_service.get_float_setting("FUZZY_THRESHOLD", 88.0) == 88.0
