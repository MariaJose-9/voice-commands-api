"""Normalization pipeline entrypoint."""

from __future__ import annotations

from typing import Optional

from app.config import (
    ENABLE_OLLAMA_FALLBACK,
    ENABLE_SEMANTIC_MATCHER,
    FUZZY_THRESHOLD,
    MAX_TEXT_LENGTH,
    SEMANTIC_CONFIRMATION_THRESHOLD,
    SEMANTIC_THRESHOLD,
)
from app.entity_extractor import extract_entities
from app.fuzzy_matcher import match_by_fuzzy
from app.multi_command import deduplicate_commands, split_into_fragments
from app.ollama_fallback import ollama_fallback_normalize
from app.preprocessor import normalize_text
from app.rule_matcher import match_by_rules
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.semantic_matcher import match_by_semantic


def _unknown_command(raw_fragment: str) -> NormalizedCommand:
    """Return a fallback UNKNOWN command."""

    return NormalizedCommand(
        command=CommandName.UNKNOWN,
        confidence=0.0,
        method=MatchMethod.unknown,
        raw_fragment=raw_fragment,
    )


def normalize_command_text(
    text: str,
    language_hint: Optional[str] = None,
    context: Optional[dict] = None,
) -> NormalizeResponse:
    """Normalize free-form transcribed voice text into canonical commands."""

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

    if len(text) > MAX_TEXT_LENGTH:
        unknown = _unknown_command(text[:MAX_TEXT_LENGTH])
        return NormalizeResponse(
            ok=False,
            raw_text=raw_text,
            normalized_text="",
            language=language_hint,
            commands=[unknown],
            needs_confirmation=True,
            message=f"Text input exceeds maximum length of {MAX_TEXT_LENGTH} characters.",
        )

    normalized_text = normalize_text(text)
    fragments = split_into_fragments(normalized_text)
    commands: list[NormalizedCommand] = []

    for fragment in fragments:
        entities = extract_entities(fragment)
        rule_matches = match_by_rules(fragment, entities)
        if rule_matches:
            commands.extend(rule_matches)
            continue

        fuzzy_match = match_by_fuzzy(fragment, threshold=FUZZY_THRESHOLD)
        if fuzzy_match is not None:
            commands.append(fuzzy_match)
            continue

        semantic_match = None
        if ENABLE_SEMANTIC_MATCHER:
            semantic_match = match_by_semantic(
                fragment,
                threshold=SEMANTIC_THRESHOLD,
                confirmation_threshold=SEMANTIC_CONFIRMATION_THRESHOLD,
            )
            if semantic_match is not None and semantic_match.confidence >= SEMANTIC_THRESHOLD:
                commands.append(semantic_match)
                continue

        if ENABLE_OLLAMA_FALLBACK:
            llm_response = ollama_fallback_normalize(
                text=fragment,
                normalized_text=fragment,
                language_hint=language_hint,
            )
            if llm_response is not None:
                commands.extend(llm_response.commands)
                continue

        if semantic_match is not None:
            commands.append(semantic_match)

    commands = deduplicate_commands(commands)

    if not commands:
        commands = [_unknown_command(normalized_text)]

    needs_confirmation = (
        not commands
        or any(command.confidence < SEMANTIC_THRESHOLD for command in commands)
        or any(command.command == CommandName.UNKNOWN for command in commands)
    )

    _ = context

    return NormalizeResponse(
        ok=all(command.command != CommandName.UNKNOWN for command in commands),
        raw_text=raw_text,
        normalized_text=normalized_text,
        language=language_hint,
        commands=commands,
        needs_confirmation=needs_confirmation,
        message=None,
    )
