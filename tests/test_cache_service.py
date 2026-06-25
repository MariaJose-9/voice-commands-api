from __future__ import annotations

import app.services.cache_service as cache_service


def test_clear_all_runtime_caches(monkeypatch) -> None:
    calls = []

    monkeypatch.setattr(cache_service, "clear_catalog_cache", lambda: calls.append("catalog"))
    monkeypatch.setattr(
        cache_service,
        "clear_entity_catalog_cache",
        lambda: calls.append("entities"),
    )
    monkeypatch.setattr(cache_service, "clear_fuzzy_cache", lambda: calls.append("fuzzy"))
    monkeypatch.setattr(cache_service, "clear_semantic_cache", lambda: calls.append("semantic"))

    cache_service.clear_all_runtime_caches()

    assert calls == ["catalog", "entities", "fuzzy", "semantic"]


def test_rebuild_runtime_indexes_when_semantic_enabled(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(
        cache_service,
        "clear_all_runtime_caches",
        lambda: calls.append("cleared"),
    )
    monkeypatch.setattr(cache_service, "ENABLE_SEMANTIC_MATCHER", True)
    monkeypatch.setattr(
        cache_service,
        "warmup_semantic_matcher",
        lambda force_rebuild=False: {
            "enabled": True,
            "model_loaded": True,
            "index_built": True,
            "examples_indexed": 5,
            "model_name": "fake-model",
            "force_rebuild": force_rebuild,
        },
    )

    payload = cache_service.rebuild_runtime_indexes()

    assert calls == ["cleared"]
    assert payload["catalog_cache_cleared"] is True
    assert payload["semantic_rebuilt"] is True
    assert payload["semantic"]["force_rebuild"] is True


def test_rebuild_runtime_indexes_when_semantic_disabled(monkeypatch) -> None:
    monkeypatch.setattr(cache_service, "clear_all_runtime_caches", lambda: None)
    monkeypatch.setattr(cache_service, "ENABLE_SEMANTIC_MATCHER", False)

    payload = cache_service.rebuild_runtime_indexes()

    assert payload == {
        "catalog_cache_cleared": True,
        "semantic_rebuilt": False,
        "semantic": None,
    }
