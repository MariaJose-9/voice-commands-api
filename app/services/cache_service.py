"""Runtime cache and index management helpers."""

from __future__ import annotations

from app.config import ENABLE_SEMANTIC_MATCHER
from app.fuzzy_matcher import clear_fuzzy_cache
from app.semantic_matcher import clear_semantic_cache, warmup_semantic_matcher
from app.services.catalog_service import clear_catalog_cache
from app.services.entity_catalog_service import clear_entity_catalog_cache


def clear_all_runtime_caches() -> None:
    """Clear runtime caches shared across matchers and catalogs."""

    clear_catalog_cache()
    clear_entity_catalog_cache()
    clear_fuzzy_cache()
    clear_semantic_cache()


def rebuild_runtime_indexes() -> dict:
    """Clear caches and rebuild semantic indexes when enabled."""

    clear_all_runtime_caches()
    semantic_payload = None
    semantic_rebuilt = False

    if ENABLE_SEMANTIC_MATCHER:
        semantic_payload = warmup_semantic_matcher(force_rebuild=True)
        semantic_rebuilt = bool(semantic_payload.get("index_built"))

    return {
        "catalog_cache_cleared": True,
        "semantic_rebuilt": semantic_rebuilt,
        "semantic": semantic_payload,
    }
