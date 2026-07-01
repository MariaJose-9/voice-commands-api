"""Normalization pipeline entrypoint."""

from __future__ import annotations

from typing import Optional

import app.services.runtime_settings_service as runtime_settings_service
from app.config import (
    ENABLE_OLLAMA_FALLBACK,
    ENABLE_SEMANTIC_MATCHER,
    FUZZY_THRESHOLD,
    LLM_COMMAND_MODE,
    MAX_TEXT_LENGTH,
    SEMANTIC_CONFIRMATION_THRESHOLD,
    SEMANTIC_THRESHOLD,
)
from app.entity_extractor import extract_entities
from app.fuzzy_matcher import match_by_fuzzy
from app.multi_command import deduplicate_commands, split_into_fragments
from app.ollama_fallback import interpret_commands_with_llm, ollama_fallback_normalize
from app.preprocessor import normalize_text
from app.rule_matcher import match_by_rules
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.semantic_matcher import match_by_semantic
from app.services.command_merge_service import merge_command_results
from app.services.completeness_checker import check_command_completeness


def _unknown_command(raw_fragment: str) -> NormalizedCommand:
    """Return a fallback UNKNOWN command."""

    return NormalizedCommand(
        command=CommandName.UNKNOWN,
        confidence=0.0,
        method=MatchMethod.unknown,
        raw_fragment=raw_fragment,
    )


def _match_fragment_by_rules(fragment: str) -> list[NormalizedCommand]:
    """Return rule matches for a fragment, including simple sequential splits."""

    entities = extract_entities(fragment)
    rule_matches = match_by_rules(fragment, entities)
    if not rule_matches:
        return []

    if len(rule_matches) > 1:
        return rule_matches

    split_points = [
        " derecha ",
        " izquierda ",
        " arriba ",
        " abajo ",
        " right ",
        " left ",
        " up ",
        " down ",
    ]
    for split_point in split_points:
        if split_point not in f" {fragment} ":
            continue

        token = split_point.strip()
        before, _, after = fragment.partition(token)
        subfragments = [before.strip(), token, after.strip()]
        commands: list[NormalizedCommand] = []
        for subfragment in subfragments:
            if not subfragment:
                continue
            sub_entities = extract_entities(subfragment)
            sub_matches = match_by_rules(subfragment, sub_entities)
            commands.extend(sub_matches)
        if len(commands) > len(rule_matches):
            return commands

    return rule_matches


def _build_base_response(
    *,
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str],
    commands: list[NormalizedCommand],
    confirmation_threshold: float,
    message: Optional[str] = None,
) -> NormalizeResponse:
    commands = deduplicate_commands(commands)
    if not commands:
        commands = [_unknown_command(normalized_text)]

    needs_confirmation = (
        not commands
        or any(command.confidence < confirmation_threshold for command in commands)
        or any(command.command == CommandName.UNKNOWN for command in commands)
    )
    return NormalizeResponse(
        ok=all(command.command != CommandName.UNKNOWN for command in commands),
        raw_text=raw_text,
        normalized_text=normalized_text,
        language=language_hint,
        commands=commands,
        needs_confirmation=needs_confirmation,
        message=message,
    )


def _should_call_llm(
    *,
    mode: str,
    base_response: NormalizeResponse,
    completeness_should_call_llm: bool,
    coverage_score: float,
) -> tuple[bool, Optional[str]]:
    if mode == "off":
        return False, "LLM skipped"
    if mode == "primary":
        return True, "LLM used: primary"

    fallback_condition = (
        not base_response.commands
        or base_response.needs_confirmation
        or any(command.command == CommandName.UNKNOWN for command in base_response.commands)
    )
    if mode == "fallback":
        return (
            (True, "LLM used: fallback_condition")
            if fallback_condition
            else (False, "LLM skipped")
        )

    if mode == "hybrid":
        if fallback_condition:
            return True, "LLM used: fallback_condition"
        if completeness_should_call_llm:
            return True, "LLM used: incomplete_result"
        if coverage_score < 0.55:
            return True, "LLM used: low_coverage"
        return False, "LLM skipped"

    return (
        (True, "LLM used: fallback_condition")
        if fallback_condition
        else (False, "LLM skipped")
    )


def _call_llm_interpreter(
    *,
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str],
    context: Optional[dict],
    previous_commands: list[NormalizedCommand],
    completeness_reason: Optional[str],
) -> Optional[NormalizeResponse]:
    try:
        return interpret_commands_with_llm(
            raw_text=raw_text,
            normalized_text=normalized_text,
            language_hint=language_hint,
            context=context,
            previous_commands=previous_commands,
            completeness_reason=completeness_reason,
        )
    except Exception:
        return None


def normalize_command_text(
    text: str,
    language_hint: Optional[str] = None,
    context: Optional[dict] = None,
) -> NormalizeResponse:
    """Normalize free-form transcribed voice text into canonical commands."""

    max_text_length = runtime_settings_service.get_int_setting(
        "MAX_TEXT_LENGTH",
        MAX_TEXT_LENGTH,
    )
    fuzzy_threshold = runtime_settings_service.get_float_setting(
        "FUZZY_THRESHOLD",
        FUZZY_THRESHOLD,
    )
    semantic_threshold = runtime_settings_service.get_float_setting(
        "SEMANTIC_THRESHOLD",
        SEMANTIC_THRESHOLD,
    )
    semantic_confirmation_threshold = runtime_settings_service.get_float_setting(
        "SEMANTIC_CONFIRMATION_THRESHOLD",
        SEMANTIC_CONFIRMATION_THRESHOLD,
    )
    enable_semantic_matcher = runtime_settings_service.get_bool_setting(
        "ENABLE_SEMANTIC_MATCHER",
        ENABLE_SEMANTIC_MATCHER,
    )
    enable_ollama_fallback = runtime_settings_service.get_bool_setting(
        "ENABLE_OLLAMA_FALLBACK",
        ENABLE_OLLAMA_FALLBACK,
    )
    llm_command_mode = runtime_settings_service.get_runtime_str_setting(
        "LLM_COMMAND_MODE",
        LLM_COMMAND_MODE,
    ).strip().lower()
    if not enable_ollama_fallback and llm_command_mode != "primary":
        llm_command_mode = "off"

    raw_text = text
    if not text or not text.strip():
        unknown = _unknown_command("")
        return NormalizeResponse(
            ok=False,
            raw_text=raw_text,
            normalized_text="",
            language=language_hint,
            commands=[unknown],
            needs_confirmation=True,
            message="Text input cannot be empty.",
        )

    if len(text) > max_text_length:
        unknown = _unknown_command(text[:max_text_length])
        return NormalizeResponse(
            ok=False,
            raw_text=raw_text,
            normalized_text="",
            language=language_hint,
            commands=[unknown],
            needs_confirmation=True,
            message=f"Text input exceeds maximum length of {max_text_length} characters.",
        )

    normalized_text = normalize_text(text)

    if llm_command_mode == "primary":
        llm_response = _call_llm_interpreter(
            raw_text=raw_text,
            normalized_text=normalized_text,
            language_hint=language_hint,
            context=context,
            previous_commands=[],
            completeness_reason="primary",
        )
        if llm_response is not None:
            return merge_command_results(
                _build_base_response(
                    raw_text=raw_text,
                    normalized_text=normalized_text,
                    language_hint=language_hint,
                    commands=[],
                    confirmation_threshold=semantic_threshold,
                    message="LLM used: primary",
                ),
                llm_response,
            )

    fragments = split_into_fragments(normalized_text)
    commands: list[NormalizedCommand] = []

    for fragment in fragments:
        rule_matches = _match_fragment_by_rules(fragment)
        if rule_matches:
            commands.extend(rule_matches)
            continue

        fuzzy_match = match_by_fuzzy(fragment, threshold=fuzzy_threshold)
        if fuzzy_match is not None:
            commands.append(fuzzy_match)
            continue

        semantic_match = None
        if enable_semantic_matcher:
            semantic_match = match_by_semantic(
                fragment,
                threshold=semantic_threshold,
                confirmation_threshold=semantic_confirmation_threshold,
            )
            if semantic_match is not None and semantic_match.confidence >= semantic_threshold:
                commands.append(semantic_match)
                continue

        if semantic_match is not None:
            commands.append(semantic_match)

    base_response = _build_base_response(
        raw_text=raw_text,
        normalized_text=normalized_text,
        language_hint=language_hint,
        commands=commands,
        confirmation_threshold=semantic_threshold,
    )
    completeness = check_command_completeness(normalized_text, base_response.commands)
    should_call_llm, llm_message = _should_call_llm(
        mode=llm_command_mode,
        base_response=base_response,
        completeness_should_call_llm=completeness.should_call_llm,
        coverage_score=completeness.coverage_score,
    )

    if not should_call_llm:
        base_response.message = llm_message if base_response.message is None else base_response.message
        return base_response

    llm_response = _call_llm_interpreter(
        raw_text=raw_text,
        normalized_text=normalized_text,
        language_hint=language_hint,
        context=context,
        previous_commands=base_response.commands,
        completeness_reason=completeness.reason,
    )
    if llm_response is None and enable_ollama_fallback and llm_command_mode == "fallback":
        llm_response = ollama_fallback_normalize(
            text=normalized_text,
            normalized_text=normalized_text,
            language_hint=language_hint,
        )

    if llm_response is None:
        base_response.message = "LLM failed, returned base parser result"
        return base_response

    merged_response = merge_command_results(base_response, llm_response)
    if merged_response.message == "Completed with LLM" and llm_message:
        merged_response.message = f"{llm_message}; Completed with LLM"
    elif merged_response.message is None:
        merged_response.message = llm_message
    return merged_response
