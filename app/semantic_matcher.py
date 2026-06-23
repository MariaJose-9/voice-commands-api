"""Semantic command matching."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Any, Optional
import concurrent.futures

import numpy as np
import yaml

from app.config import SEMANTIC_MODEL_NAME, SEMANTIC_TIMEOUT_SECONDS
from app.entity_extractor import extract_entities
from app.preprocessor import normalize_text
from app.schemas import CommandName, MatchMethod, NormalizedCommand


_CATALOG_PATH = Path(__file__).resolve().parent / "commands" / "catalog.yml"
_ENTITY_ONLY_COMMANDS = {
    CommandName.SELECT_MONITOR,
    CommandName.SET_LAYOUT,
    CommandName.SET_SIZE,
}

_MODEL: Any = None
_MODEL_LOAD_FAILED = False
_SEMANTIC_INDEX: list[dict[str, Any]] = []
_INDEX_BUILT = False
_MODEL_LOCK = Lock()
_INDEX_LOCK = Lock()


@lru_cache(maxsize=1)
def _load_catalog() -> list[dict[str, Any]]:
    """Load the command catalog from YAML once per process."""

    data = yaml.safe_load(_CATALOG_PATH.read_text(encoding="utf-8")) or {}
    return data.get("commands", [])


def _run_with_timeout(func, *args):
    """Run a callable with a bounded wait time."""

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(func, *args)
    try:
        return future.result(timeout=SEMANTIC_TIMEOUT_SECONDS)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError("semantic matcher operation timed out") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


def _get_model() -> Any:
    """Load the sentence-transformers model lazily.

    Returns None if loading fails so callers can degrade gracefully.
    """

    global _MODEL, _MODEL_LOAD_FAILED

    if _MODEL is not None:
        return _MODEL
    if _MODEL_LOAD_FAILED:
        return None

    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        if _MODEL_LOAD_FAILED:
            return None

        try:
            from sentence_transformers import SentenceTransformer

            _MODEL = SentenceTransformer(SEMANTIC_MODEL_NAME)
        except Exception:
            _MODEL_LOAD_FAILED = True
            _MODEL = None

    return _MODEL


def _cosine_similarity(vector_a: np.ndarray, vector_b: np.ndarray) -> float:
    """Compute cosine similarity between two embedding vectors."""

    norm_a = np.linalg.norm(vector_a)
    norm_b = np.linalg.norm(vector_b)
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return float(np.dot(vector_a, vector_b) / (norm_a * norm_b))


def _encode_texts(texts: list[str]) -> np.ndarray:
    """Encode texts using the lazy-loaded model."""

    model = _get_model()
    if model is None:
        raise RuntimeError("semantic model unavailable")

    embeddings = _run_with_timeout(model.encode, texts)
    return np.asarray(embeddings, dtype=float)


def _has_required_entities(command: CommandName, entities: dict[str, Any]) -> bool:
    """Validate required entities for entity-dependent commands."""

    if command == CommandName.SELECT_MONITOR:
        return entities.get("monitor") in {1, 2}
    if command == CommandName.SET_LAYOUT:
        return entities.get("layout") in {1, 2}
    if command == CommandName.SET_SIZE:
        return entities.get("size_inches") in {55, 65, 75, 95, 120}
    return True


def build_semantic_index(force_rebuild: bool = False) -> None:
    """Build the in-memory semantic index from the catalog examples."""

    global _SEMANTIC_INDEX, _INDEX_BUILT

    if _INDEX_BUILT and not force_rebuild:
        return

    with _INDEX_LOCK:
        if _INDEX_BUILT and not force_rebuild:
            return

        model = _get_model()
        if model is None:
            _SEMANTIC_INDEX = []
            _INDEX_BUILT = False
            return

        rows: list[dict[str, Any]] = []
        texts_to_encode: list[str] = []

        for entry in _load_catalog():
            command_name = CommandName(entry["command"])
            requires_entities = entry.get("requires_entities", [])
            for example in entry.get("examples", []):
                normalized_example = normalize_text(example)
                rows.append(
                    {
                        "command": command_name,
                        "example": example,
                        "normalized_example": normalized_example,
                        "requires_entities": requires_entities,
                    }
                )
                texts_to_encode.append(normalized_example)

        try:
            embeddings = _encode_texts(texts_to_encode)
        except Exception:
            _SEMANTIC_INDEX = []
            _INDEX_BUILT = False
            return

        _SEMANTIC_INDEX = []
        for row, embedding in zip(rows, embeddings):
            row["embedding"] = np.asarray(embedding, dtype=float)
            _SEMANTIC_INDEX.append(row)

        _INDEX_BUILT = True


def warmup_semantic_matcher(force_rebuild: bool = False) -> dict[str, Any]:
    """Warm up the semantic model and embedding index on demand."""

    model = _get_model()
    build_semantic_index(force_rebuild=force_rebuild)
    return {
        "enabled": True,
        "model_loaded": model is not None,
        "index_built": _INDEX_BUILT,
        "examples_indexed": len(_SEMANTIC_INDEX),
        "model_name": SEMANTIC_MODEL_NAME,
    }


def get_semantic_candidates(normalized_text: str, limit: int = 5) -> list[dict]:
    """Return the top semantic candidates for debugging."""

    build_semantic_index()
    if not _INDEX_BUILT or not _SEMANTIC_INDEX:
        return []

    try:
        query_embedding = _encode_texts([normalized_text])[0]
    except Exception:
        return []

    scored = []
    for row in _SEMANTIC_INDEX:
        similarity = _cosine_similarity(query_embedding, row["embedding"])
        scored.append(
            {
                "command": row["command"].value,
                "example": row["example"],
                "score": similarity,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def match_by_semantic(
    normalized_text: str,
    threshold: float = 0.72,
    confirmation_threshold: float = 0.62,
) -> Optional[NormalizedCommand]:
    """Return the best semantic match above the confirmation threshold."""

    build_semantic_index()
    if not _INDEX_BUILT or not _SEMANTIC_INDEX:
        return None

    entities = extract_entities(normalized_text)

    try:
        query_embedding = _encode_texts([normalized_text])[0]
    except Exception:
        return None

    best_row: Optional[dict[str, Any]] = None
    best_score = -1.0

    for row in _SEMANTIC_INDEX:
        command_name = row["command"]

        if command_name in _ENTITY_ONLY_COMMANDS and not _has_required_entities(
            command_name, entities
        ):
            continue

        similarity = _cosine_similarity(query_embedding, row["embedding"])
        if similarity > best_score:
            best_score = similarity
            best_row = row

    if best_row is None or best_score < confirmation_threshold:
        return None

    command_name = best_row["command"]
    return NormalizedCommand(
        command=command_name,
        confidence=best_score,
        method=MatchMethod.semantic,
        raw_fragment=normalized_text,
        monitor=entities.get("monitor") if command_name == CommandName.SELECT_MONITOR else None,
        layout=entities.get("layout") if command_name == CommandName.SET_LAYOUT else None,
        size_inches=(
            entities.get("size_inches") if command_name == CommandName.SET_SIZE else None
        ),
    )
