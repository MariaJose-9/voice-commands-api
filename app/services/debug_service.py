"""Shared debug helpers for the normalization pipeline."""

from __future__ import annotations

from typing import Any

from app.config import (
    ENABLE_SEMANTIC_MATCHER,
    FUZZY_THRESHOLD,
    SEMANTIC_CONFIRMATION_THRESHOLD,
    SEMANTIC_THRESHOLD,
)
from app.entity_extractor import extract_entities
from app.fuzzy_matcher import get_fuzzy_candidates, match_by_fuzzy
from app.multi_command import split_into_fragments
from app.normalizer import normalize_command_text
from app.preprocessor import normalize_text
from app.rule_matcher import match_by_rules
from app.schemas import NormalizeRequest
from app.semantic_matcher import get_semantic_candidates, match_by_semantic


def build_debug_response(payload: NormalizeRequest) -> dict[str, Any]:
    """Assemble debug data for the normalization pipeline."""

    normalized_text = normalize_text(payload.text) if payload.text else ""
    fragments = split_into_fragments(normalized_text) if normalized_text else []
    entities_by_fragment = []
    rule_matches = []
    fuzzy_candidates = []
    semantic_candidates = []

    for fragment in fragments:
        entities = extract_entities(fragment)
        rule_match_list = match_by_rules(fragment, entities)
        fuzzy_match = match_by_fuzzy(fragment, threshold=FUZZY_THRESHOLD)
        semantic_match = (
            match_by_semantic(
                fragment,
                threshold=SEMANTIC_THRESHOLD,
                confirmation_threshold=SEMANTIC_CONFIRMATION_THRESHOLD,
            )
            if ENABLE_SEMANTIC_MATCHER
            else None
        )

        entities_by_fragment.append({"fragment": fragment, "entities": entities})
        rule_matches.append(
            {
                "fragment": fragment,
                "matches": [
                    match.model_dump(mode="json") for match in rule_match_list
                ],
            }
        )
        fuzzy_candidates.append(
            {
                "fragment": fragment,
                "candidates": get_fuzzy_candidates(fragment),
                "match": (
                    fuzzy_match.model_dump(mode="json")
                    if fuzzy_match is not None
                    else None
                ),
            }
        )
        semantic_candidates.append(
            {
                "fragment": fragment,
                "candidates": (
                    get_semantic_candidates(fragment) if ENABLE_SEMANTIC_MATCHER else []
                ),
                "match": (
                    semantic_match.model_dump(mode="json")
                    if semantic_match is not None
                    else None
                ),
            }
        )

    final_response = normalize_command_text(
        text=payload.text,
        language_hint=payload.language_hint,
        context=payload.context,
    )
    return {
        "raw_text": payload.text,
        "normalized_text": normalized_text,
        "fragments": fragments,
        "entities_by_fragment": entities_by_fragment,
        "rule_matches": rule_matches,
        "fuzzy_candidates": fuzzy_candidates,
        "semantic_candidates": semantic_candidates,
        "final_response": final_response.model_dump(mode="json"),
    }
