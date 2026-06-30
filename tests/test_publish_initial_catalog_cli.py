from __future__ import annotations

import app.db.publish_initial_catalog as publish_initial_module


def test_publish_initial_catalog_cli_helper_uses_publish_service(monkeypatch) -> None:
    class FakeSessionContext:
        def __enter__(self):
            return "fake-session"

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeSessionFactory:
        def __call__(self, engine):
            return FakeSessionContext()

    calls = []

    def fake_publish_catalog(session, actor_user_id=None):
        calls.append((session, actor_user_id))
        return {
            "published": True,
            "version_number": 1,
            "commands": 25,
            "examples": 383,
            "semantic_rebuilt": False,
        }

    monkeypatch.setattr(publish_initial_module, "DBSession", FakeSessionFactory())
    monkeypatch.setattr(publish_initial_module, "engine", object())
    monkeypatch.setattr(publish_initial_module, "publish_catalog", fake_publish_catalog)

    result = publish_initial_module.publish_initial_catalog()

    assert result["published"] is True
    assert result["version_number"] == 1
    assert calls == [("fake-session", None)]
