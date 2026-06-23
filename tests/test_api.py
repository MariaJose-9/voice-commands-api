from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
from app.schemas import CommandName


client = TestClient(main_module.app)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "voice-command-api"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_catalog_endpoint() -> None:
    response = client.get("/v1/commands/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert "commands" in payload
    assert any(item["command"] == "SELECT_MONITOR" for item in payload["commands"])


def test_examples_endpoint() -> None:
    response = client.get("/v1/commands/examples")
    assert response.status_code == 200
    payload = response.json()
    assert "examples" in payload
    assert len(payload["examples"]) >= 1
    assert "request" in payload["examples"][0]
    assert "response" in payload["examples"][0]


def test_normalize_endpoint() -> None:
    response = client.post(
        "/v1/commands/normalize",
        json={"text": "monitor two and zoom in", "language_hint": "en"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["language"] == "en"
    assert [command["command"] for command in payload["commands"]] == [
        CommandName.SELECT_MONITOR.value,
        CommandName.ZOOM_IN.value,
    ]


def test_normalize_endpoint_empty_text_returns_unknown() -> None:
    response = client.post("/v1/commands/normalize", json={"text": ""})
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["needs_confirmation"] is True
    assert payload["commands"][0]["command"] == CommandName.UNKNOWN.value


def test_normalize_endpoint_internal_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(main_module, "normalize_command_text", raise_error)
    response = client.post("/v1/commands/normalize", json={"text": "left"})
    assert response.status_code == 500
    assert response.json() == {"detail": "Internal error while normalizing commands."}


def test_debug_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "ENV", "development")
    monkeypatch.setattr(main_module, "ENABLE_SEMANTIC_MATCHER", False)
    monkeypatch.setattr(
        main_module,
        "get_fuzzy_candidates",
        lambda normalized_text, limit=5: [
            {"command": "MOVE_LEFT", "example": "left", "score": 100.0}
        ],
    )
    monkeypatch.setattr(
        main_module,
        "get_semantic_candidates",
        lambda normalized_text, limit=5: [],
    )

    response = client.post("/v1/commands/debug", json={"text": "monitor two and left"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["raw_text"] == "monitor two and left"
    assert payload["normalized_text"] == "monitor two and left"
    assert payload["fragments"] == ["monitor two", "left"]
    assert len(payload["entities_by_fragment"]) == 2
    assert "final_response" in payload
    assert [command["command"] for command in payload["final_response"]["commands"]] == [
        CommandName.SELECT_MONITOR.value,
        CommandName.MOVE_LEFT.value,
    ]


def test_debug_endpoint_hidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "ENV", "production")
    response = client.post("/v1/commands/debug", json={"text": "left"})
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_warmup_endpoint_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "ENABLE_SEMANTIC_MATCHER", False)
    response = client.post("/v1/commands/warmup")
    assert response.status_code == 200
    assert response.json() == {
        "enabled": False,
        "message": "Semantic matcher is disabled.",
    }


def test_warmup_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "ENABLE_SEMANTIC_MATCHER", True)
    monkeypatch.setattr(
        main_module,
        "warmup_semantic_matcher",
        lambda: {
            "enabled": True,
            "model_loaded": True,
            "index_built": True,
            "examples_indexed": 10,
            "model_name": "fake-model",
        },
    )
    response = client.post("/v1/commands/warmup")
    assert response.status_code == 200
    assert response.json()["index_built"] is True
