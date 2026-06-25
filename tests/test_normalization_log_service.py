from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.services.normalization_log_service as log_service
from app.db.models import NormalizationLog, ReviewStatus
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand


def test_save_normalization_log_marks_unknown_as_pending(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(log_service, "SessionFactory", Session)
    monkeypatch.setattr(log_service, "engine", engine)
    monkeypatch.setattr(log_service, "ENABLE_NORMALIZATION_LOGS", True)

    response = NormalizeResponse(
        ok=False,
        raw_text="abracadabra",
        normalized_text="abracadabra",
        language=None,
        commands=[
            NormalizedCommand(
                command=CommandName.UNKNOWN,
                confidence=0.0,
                method=MatchMethod.unknown,
                raw_fragment="abracadabra",
            )
        ],
        needs_confirmation=True,
        message=None,
    )

    log_service.save_normalization_log(
        raw_text="abracadabra",
        normalized_text="abracadabra",
        language=None,
        response=response,
    )

    with Session(engine) as session:
        row = session.exec(select(NormalizationLog)).first()
        assert row is not None
        assert row.review_status == ReviewStatus.PENDING
        assert row.needs_confirmation is True
        assert row.top_confidence == 0.0
