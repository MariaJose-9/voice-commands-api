"""Shared debug helpers for the normalization pipeline."""

from __future__ import annotations

from typing import Any

from app.config import (
    DEBUG_LLM_PROMPT,
    ENABLE_OLLAMA_FALLBACK,
    ENABLE_SEMANTIC_MATCHER,
    ENV,
    FUZZY_THRESHOLD,
    LLM_COMMAND_MODE,
    OLLAMA_MODEL,
    SEMANTIC_CONFIRMATION_THRESHOLD,
    SEMANTIC_THRESHOLD,
)
from app.entity_extractor import extract_entities
from app.fuzzy_matcher import get_fuzzy_candidates, match_by_fuzzy
from app.multi_command import split_into_fragments
from app.normalizer import _build_base_response, normalize_command_text
from app.ollama_fallback import build_llm_command_prompt, interpret_commands_with_llm
from app.preprocessor import normalize_text
from app.rule_matcher import match_by_rules
from app.schemas import CommandName, NormalizeRequest
from app.semantic_matcher import get_semantic_candidates, match_by_semantic
from app.services.command_canonicalization_service import canonicalize_commands
from app.services.command_dedup_service import get_command_semantic_key
from app.services.command_merge_service import (
    deduplicate_commands_semantically,
    detect_command_conflicts,
    merge_command_results,
)
from app.services.completeness_checker import (
    check_command_completeness,
    get_uncovered_text,
)
from app.services import runtime_settings_service


def _llm_should_call(mode: str, enabled: bool, base_response, completeness) -> tuple[bool, str | None]:
    if not enabled and mode != "primary":
        return False, "disabled"
    if mode == "off":
        return False, "off"
    if mode == "primary":
        return True, "primary"

    fallback_condition = (
        not base_response.commands
        or base_response.needs_confirmation
        or any(command.command == CommandName.UNKNOWN for command in base_response.commands)
    )
    if mode == "fallback":
        return (
            (True, "fallback_condition")
            if fallback_condition
            else (False, None)
        )
    if mode == "hybrid":
        if fallback_condition:
            return True, "fallback_condition"
        if completeness.should_call_llm:
            return True, completeness.reason
    return False, None


def _method_name(command) -> str:
    return command.method.value if hasattr(command.method, "value") else str(command.method)


def _build_merge_debug(commands) -> dict[str, Any]:
    deduplicated_commands = deduplicate_commands_semantically(commands)
    kept_by_key = {
        get_command_semantic_key(command): command
        for command in deduplicated_commands
    }
    grouped: dict[tuple, list] = {}
    for command in commands:
        grouped.setdefault(get_command_semantic_key(command), []).append(command)

    duplicates_removed = []
    for semantic_key, grouped_commands in grouped.items():
        if len(grouped_commands) <= 1:
            continue

        kept_command = kept_by_key.get(semantic_key)
        kept_index = next(
            (
                index
                for index, command in enumerate(grouped_commands)
                if command is kept_command
            ),
            0,
        )
        removed_methods = [
            _method_name(command)
            for index, command in enumerate(grouped_commands)
            if index != kept_index
        ]
        if not removed_methods:
            continue

        duplicates_removed.append(
            {
                "semantic_key": list(semantic_key),
                "kept_method": _method_name(grouped_commands[kept_index]),
                "removed_methods": removed_methods,
            }
        )

    return {
        "deduplicated": True,
        "duplicates_removed": duplicates_removed,
        "conflicts": detect_command_conflicts(commands),
    }


def build_debug_response(payload: NormalizeRequest) -> dict[str, Any]:
    """Assemble debug data for the normalization pipeline."""

    normalized_text = normalize_text(payload.text) if payload.text else ""
    fragments = split_into_fragments(normalized_text) if normalized_text else []
    entities_by_fragment = []
    rule_matches = []
    fuzzy_candidates = []
    semantic_candidates = []
    base_commands = []

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

        if rule_match_list:
            base_commands.extend(rule_match_list)
        elif fuzzy_match is not None:
            base_commands.append(fuzzy_match)
        elif semantic_match is not None:
            base_commands.append(semantic_match)

    base_response = _build_base_response(
        raw_text=payload.text,
        normalized_text=normalized_text,
        language_hint=payload.language_hint,
        commands=base_commands,
        confirmation_threshold=SEMANTIC_THRESHOLD,
    )
    final_response = normalize_command_text(
        text=payload.text,
        language_hint=payload.language_hint,
        context=payload.context,
    )
    completeness = check_command_completeness(normalized_text, base_response.commands)
    completeness_payload = completeness.model_dump(mode="json")
    completeness_payload["uncovered_text"] = get_uncovered_text(
        normalized_text,
        base_response.commands,
    )

    llm_mode = runtime_settings_service.get_runtime_str_setting(
        "LLM_COMMAND_MODE",
        LLM_COMMAND_MODE,
    ).strip().lower()
    llm_enabled = runtime_settings_service.get_bool_setting(
        "ENABLE_OLLAMA_FALLBACK",
        ENABLE_OLLAMA_FALLBACK,
    )
    should_call_llm, llm_reason = _llm_should_call(
        llm_mode,
        llm_enabled,
        base_response,
        completeness,
    )
    llm_response = None
    if should_call_llm:
        llm_response = interpret_commands_with_llm(
            raw_text=payload.text,
            normalized_text=normalized_text,
            language_hint=payload.language_hint,
            context=payload.context,
            previous_commands=base_response.commands,
            completeness_reason=completeness.reason,
        )
    if llm_response is not None:
        llm_response.commands = canonicalize_commands(llm_response.commands)
    llm_payload = {
        "mode": llm_mode,
        "enabled": bool(llm_enabled or llm_mode == "primary"),
        "should_call": should_call_llm,
        "reason": llm_reason,
        "called": should_call_llm,
        "success": llm_response is not None,
        "model": runtime_settings_service.get_runtime_str_setting(
            "OLLAMA_MODEL",
            OLLAMA_MODEL,
        ),
        "merged": False,
    }
    if llm_response is not None:
        merged = merge_command_results(
            base_response,
            llm_response,
            normalized_text=normalized_text,
            raw_text=payload.text,
        )
        llm_payload["merged"] = (
            merged.model_dump(mode="json") != base_response.model_dump(mode="json")
        )
    merge_payload = _build_merge_debug(
        base_response.commands + (llm_response.commands if llm_response else [])
    )
    if ENV == "development" and DEBUG_LLM_PROMPT:
        llm_payload["prompt"] = build_llm_command_prompt(
            raw_text=payload.text,
            normalized_text=normalized_text,
            language_hint=payload.language_hint,
            context=payload.context,
            previous_commands=base_response.commands,
            completeness_reason=completeness.reason,
        )
    return {
        "raw_text": payload.text,
        "normalized_text": normalized_text,
        "fragments": fragments,
        "entities_by_fragment": entities_by_fragment,
        "rule_matches": rule_matches,
        "fuzzy_candidates": fuzzy_candidates,
        "semantic_candidates": semantic_candidates,
        "completeness": completeness_payload,
        "llm": llm_payload,
        "merge": merge_payload,
        "final_response": final_response.model_dump(mode="json"),
    }
