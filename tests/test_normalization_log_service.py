from __future__ import annotations

import pytest

pytest.importorskip("sqlalchemy")
pytest.importorskip("sqlmodel")

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.services.normalization_log_service as log_service
from app.db.models import NormalizationLog, ReviewStatus
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services import size_validation_service


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


def test_save_normalization_log_includes_llm_metadata(monkeypatch) -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(log_service, "SessionFactory", Session)
    monkeypatch.setattr(log_service, "engine", engine)
    monkeypatch.setattr(log_service, "ENABLE_NORMALIZATION_LOGS", True)
    monkeypatch.setattr(
        log_service.runtime_settings_service,
        "get_runtime_str_setting",
        lambda key, default: {"LLM_COMMAND_MODE": "hybrid", "OLLAMA_MODEL": "qwen2.5:3b"}.get(key, default),
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {"MIN_SIZE_INCHES": 40, "MAX_SIZE_INCHES": 150}[key],
    )

    response = NormalizeResponse(
        ok=True,
        raw_text="redimensiona a 72 pulgadas el monitor 1",
        normalized_text="redimensiona a 72 pulgadas el monitor 1",
        language="es",
        commands=[
            NormalizedCommand(
                command=CommandName.SELECT_MONITOR,
                confidence=0.95,
                method=MatchMethod.entity_rule,
                monitor=1,
                raw_fragment="monitor 1",
            ),
            NormalizedCommand(
                command=CommandName.SET_SIZE,
                confidence=0.95,
                method=MatchMethod.llm,
                size_inches=72,
                raw_fragment="redimensiona a 72 pulgadas",
            ),
        ],
        needs_confirmation=False,
        message="LLM used: incomplete_result; Completed with LLM",
    )

    log_service.save_normalization_log(
        raw_text=response.raw_text,
        normalized_text=response.normalized_text,
        language=response.language,
        response=response,
    )

    with Session(engine) as session:
        row = session.exec(select(NormalizationLog)).first()
        metadata = row.result_json["metadata"]
        assert metadata["llm_mode"] == "hybrid"
        assert metadata["llm_called"] is True
        assert metadata["llm_reason"] == "incomplete_result"
        assert metadata["llm_model"] == "qwen2.5:3b"
        assert metadata["merged_with_llm"] is True
        assert "completeness_score" in metadata


def test_save_normalization_log_marks_llm_not_called(monkeypatch) -> None:
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
        ok=True,
        raw_text="monitor 1",
        normalized_text="monitor 1",
        language="es",
        commands=[
            NormalizedCommand(
                command=CommandName.SELECT_MONITOR,
                confidence=1.0,
                method=MatchMethod.entity_rule,
                monitor=1,
                raw_fragment="monitor 1",
            )
        ],
        needs_confirmation=False,
        message="LLM skipped",
    )

    log_service.save_normalization_log(
        raw_text=response.raw_text,
        normalized_text=response.normalized_text,
        language=response.language,
        response=response,
    )

    with Session(engine) as session:
        row = session.exec(select(NormalizationLog)).first()
        metadata = row.result_json["metadata"]
        assert metadata["llm_called"] is False
        assert metadata["merged_with_llm"] is False
