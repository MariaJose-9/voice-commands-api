from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db.models import AppSetting
from app.services.settings_service import is_catalog_dirty, set_catalog_dirty


def test_catalog_dirty_roundtrip() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        assert is_catalog_dirty(session) is False
        set_catalog_dirty(session, True)
        assert is_catalog_dirty(session) is True
        set_catalog_dirty(session, False)
        assert is_catalog_dirty(session) is False
        settings = session.exec(select(AppSetting)).all()
        assert len(settings) == 1
        assert settings[0].key == "CATALOG_DIRTY"
