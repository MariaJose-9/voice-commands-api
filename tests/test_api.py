from __future__ import annotations

import importlib

from fastapi.testclient import TestClient
import pytest

import app.main as main_module
import app.db.seed as seed_module
import app.db.session as session_module
import app.db.models as db_models
from app.schemas import CommandName


admin_router_module = importlib.import_module("app.admin.router")


client = TestClient(main_module.app)


def test_root() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {"message": "voice-command-api"}


def test_health() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_db_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "check_database_health", lambda: True)
    response = client.get("/health/db")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


def test_health_db_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def raise_error():
        raise RuntimeError("db down")

    monkeypatch.setattr(main_module, "check_database_health", raise_error)
    response = client.get("/health/db")
    assert response.status_code == 503
    assert response.json() == {"status": "error", "database": "unavailable"}


def test_catalog_endpoint() -> None:
    response = client.get("/v1/commands/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert "source" in payload
    assert "metadata" in payload
    assert "commands" in payload
    assert len(payload["commands"]) >= 1
    assert all("command" in item for item in payload["commands"])
    assert payload["metadata"]["command_count"] >= 1


def test_catalog_endpoint_yaml_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main_module,
        "get_active_catalog",
        lambda: [{"command": "SELECT_MONITOR", "examples": ["monitor one"]}],
    )
    monkeypatch.setattr(
        main_module,
        "get_catalog_metadata",
        lambda: {
            "source": "yaml_fallback",
            "command_count": 1,
            "example_count": 1,
            "cached": True,
        },
    )

    response = client.get("/v1/commands/catalog")
    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "yaml_fallback"
    assert payload["commands"][0]["command"] == "SELECT_MONITOR"
    assert payload["metadata"]["source"] == "yaml_fallback"


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


def test_normalize_endpoint_does_not_fail_when_log_save_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        main_module,
        "save_normalization_log",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    response = client.post(
        "/v1/commands/normalize",
        json={"text": "left", "language_hint": "en"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["commands"][0]["command"] == CommandName.MOVE_LEFT.value


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
    monkeypatch.setattr(
        main_module,
        "build_debug_response",
        lambda payload: {
            "raw_text": payload.text,
            "normalized_text": payload.text,
            "fragments": ["monitor two", "left"],
            "entities_by_fragment": [{}, {}],
            "rule_matches": [],
            "fuzzy_candidates": [],
            "semantic_candidates": [],
            "final_response": {
                "commands": [
                    {"command": CommandName.SELECT_MONITOR.value},
                    {"command": CommandName.MOVE_LEFT.value},
                ]
            },
        },
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


def test_admin_tester_requires_login() -> None:
    response = client.get("/admin/tester", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_audio_logs_requires_login() -> None:
    response = client.get("/admin/audio-logs", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_audio_tester_requires_login() -> None:
    response = client.get("/admin/audio-tester", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


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


def test_reload_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "ENV", "development")
    monkeypatch.setattr(
        main_module,
        "rebuild_runtime_indexes",
        lambda: {
            "catalog_cache_cleared": True,
            "semantic_rebuilt": True,
            "semantic": {
                "enabled": True,
                "model_loaded": True,
                "index_built": True,
                "examples_indexed": 10,
                "model_name": "fake-model",
            },
        },
    )

    response = client.post("/v1/commands/reload")
    assert response.status_code == 200
    payload = response.json()
    assert payload["catalog_cache_cleared"] is True
    assert payload["semantic_rebuilt"] is True
    assert payload["semantic"]["index_built"] is True


def test_reload_endpoint_hidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "ENV", "production")
    response = client.post("/v1/commands/reload")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_admin_dev_seed_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSessionContext:
        def __enter__(self):
            return "fake-session"

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeSessionFactory:
        def __call__(self, engine):
            return FakeSessionContext()

    monkeypatch.setattr(main_module, "ENV", "development")
    monkeypatch.setattr(session_module, "Session", FakeSessionFactory())
    monkeypatch.setattr(session_module, "engine", object())
    monkeypatch.setattr(
        seed_module,
        "run_seed",
        lambda session: {
            "commands": {"commands_created": 1, "examples_created": 2},
            "entities": {"entity_types": 3},
            "settings": {"settings_created": 5},
            "admin": {"admin_created": True, "email": "admin@example.com"},
        },
    )

    response = client.post("/admin/dev/seed")
    assert response.status_code == 200
    assert response.json()["commands"]["commands_created"] == 1


def test_admin_dev_seed_hidden_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "ENV", "production")
    response = client.post("/admin/dev/seed")
    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_admin_redirects_to_login_without_session() -> None:
    response = client.get("/admin", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_admin_login_fails_with_invalid_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(admin_router_module, "authenticate_admin_user", lambda email, password: None)
    response = client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "wrong"},
    )
    assert response.status_code == 401
    assert "Invalid email or password." in response.text


def test_admin_login_sets_cookie_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeUser:
        id = 1
        email = "admin@example.com"
        role = "admin"

    monkeypatch.setattr(
        admin_router_module,
        "authenticate_admin_user",
        lambda email, password: FakeUser(),
    )
    monkeypatch.setattr(
        admin_router_module,
        "create_session_token",
        lambda user: "signed-token",
    )

    response = client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/admin"
    assert "voice_admin_session=signed-token" in response.headers["set-cookie"]


def test_admin_login_sets_secure_cookie_in_production(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeUser:
        id = 1
        email = "admin@example.com"
        role = "admin"

    monkeypatch.setattr(admin_router_module, "ENV", "production")
    monkeypatch.setattr(
        admin_router_module,
        "authenticate_admin_user",
        lambda email, password: FakeUser(),
    )
    monkeypatch.setattr(
        admin_router_module,
        "create_session_token",
        lambda user: "signed-token",
    )

    response = client.post(
        "/admin/login",
        data={"email": "admin@example.com", "password": "admin123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "Secure" in response.headers["set-cookie"]
