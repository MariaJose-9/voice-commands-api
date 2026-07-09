"""Fuzzy command matching."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from rapidfuzz import fuzz

from app.entity_extractor import extract_entities
from app.preprocessor import normalize_text
from app.schemas import CommandName, MatchMethod, NormalizedCommand
from app.services.catalog_service import clear_catalog_cache, get_active_catalog


_ENTITY_ONLY_COMMANDS = {
    CommandName.SELECT_MONITOR,
    CommandName.SET_LAYOUT,
    CommandName.SET_SIZE,
}


@lru_cache(maxsize=1)
def _flatten_examples() -> list[dict[str, Any]]:
    """Expand catalog entries to normalized example rows for scoring."""

    flattened: list[dict[str, Any]] = []
    for entry in get_active_catalog():
        try:
            command_name = CommandName(entry["command"])
        except ValueError:
            continue
        requires_entities = entry.get("requires_entities", [])
        for example in entry.get("examples", []):
            flattened.append(
                {
                    "command": command_name,
                    "example": example,
                    "normalized_example": normalize_text(example),
                    "requires_entities": requires_entities,
                }
            )
    return flattened


def clear_fuzzy_cache() -> None:
    """Clear local fuzzy caches and the shared catalog cache."""

    _flatten_examples.cache_clear()
    clear_catalog_cache()


def _score_text(query: str, candidate: str) -> float:
    """Return a fuzzy score in the 0-100 range."""

    scores = [
        float(fuzz.WRatio(query, candidate)),
        float(fuzz.token_set_ratio(query, candidate)),
    ]
    if min(len(query), len(candidate)) > 5 or max(len(query), len(candidate)) <= 6:
        scores.append(float(fuzz.partial_ratio(query, candidate)))
    return max(scores)


def _has_required_entities(command: CommandName, entities: dict[str, Any]) -> bool:
    """Validate required entities for entity-dependent commands."""

    if command == CommandName.SELECT_MONITOR:
        return entities.get("monitor") in {1, 2}
    if command == CommandName.SET_LAYOUT:
        return entities.get("layout") in {1, 2}
    if command == CommandName.SET_SIZE:
        return isinstance(entities.get("size_inches"), int) and entities.get("size_inches") > 0
    return True


def get_fuzzy_candidates(normalized_text: str, limit: int = 5) -> list[dict]:
    """Return the top fuzzy candidates for debugging."""

    scored = []
    for row in _flatten_examples():
        score = _score_text(normalized_text, row["normalized_example"])
        scored.append(
            {
                "command": row["command"].value,
                "example": row["example"],
                "score": score,
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[:limit]


def match_by_fuzzy(
    normalized_text: str, threshold: float = 88.0
) -> Optional[NormalizedCommand]:
    """Return the best fuzzy match above the threshold, or None."""

    entities = extract_entities(normalized_text)
    best_row: Optional[dict[str, Any]] = None
    best_score = 0.0

    for row in _flatten_examples():
        command_name = row["command"]

        if command_name in _ENTITY_ONLY_COMMANDS and not _has_required_entities(
            command_name, entities
        ):
            continue

        score = _score_text(normalized_text, row["normalized_example"])
        if score > best_score:
            best_score = score
            best_row = row

    if best_row is None or best_score < threshold:
        return None

    command_name = best_row["command"]
    return NormalizedCommand(
        command=command_name,
        confidence=best_score / 100.0,
        method=MatchMethod.fuzzy,
        raw_fragment=normalized_text,
        monitor=entities.get("monitor") if command_name == CommandName.SELECT_MONITOR else None,
        layout=entities.get("layout") if command_name == CommandName.SET_LAYOUT else None,
        size_inches=(
            entities.get("size_inches") if command_name == CommandName.SET_SIZE else None
        ),
    )
