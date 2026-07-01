"""Detect incomplete command normalization results."""

from __future__ import annotations

import re
from typing import Optional

from pydantic import BaseModel, Field

from app.schemas import CommandName, NormalizedCommand


_IMPORTANT_STOPWORDS = {
    "a",
    "al",
    "and",
    "de",
    "del",
    "el",
    "en",
    "it",
    "la",
    "lo",
    "los",
    "me",
    "monitor",
    "pantalla",
    "please",
    "por",
    "screen",
    "the",
    "to",
    "un",
    "una",
    "uno",
    "y",
}

_SIZE_INTENT_PATTERN = re.compile(
    r"\b("
    r"redimensiona|redimensionar|resize|"
    r"cambia\s+tamano|cambia\s+tamano|cambiar\s+tamano|cambiar\s+tamano|"
    r"ajusta\s+tamano|ajusta\s+tamano|tamano|pulgadas?|inches?|"
    r"escala|escalar|dimensiona"
    r")\b"
)
_SIZE_NUMBER_PATTERN = re.compile(r"\b\d{2,3}\b")
_INCREASE_INTENT_PATTERN = re.compile(
    r"\b("
    r"grande|mas\s+grande|agranda|aumentar|aumenta|sube\s+tamano|"
    r"subele|bigger|larger|increase"
    r")\b"
)
_DECREASE_INTENT_PATTERN = re.compile(
    r"\b("
    r"pequeno|chico|mas\s+pequeno|reduce|reducir|achica|baja\s+tamano|"
    r"smaller|decrease"
    r")\b"
)
_DIRECTION_PATTERNS = {
    CommandName.MOVE_LEFT: re.compile(r"\b(izquierda|left)\b"),
    CommandName.MOVE_RIGHT: re.compile(r"\b(derecha|right)\b"),
    CommandName.MOVE_UP: re.compile(r"\b(arriba|up)\b"),
    CommandName.MOVE_DOWN: re.compile(r"\b(abajo|down)\b"),
}


class CompletenessResult(BaseModel):
    """Result of checking whether normalized commands cover the input text."""

    is_complete: bool
    should_call_llm: bool
    reason: Optional[str] = None
    unresolved_intents: list[str] = Field(default_factory=list)
    coverage_score: float


def _command_names(commands: list[NormalizedCommand]) -> set[CommandName]:
    return {command.command for command in commands}


def _has_absolute_size_intent(normalized_text: str) -> bool:
    return bool(_SIZE_INTENT_PATTERN.search(normalized_text)) and bool(
        _SIZE_NUMBER_PATTERN.search(normalized_text)
    )


def _important_words(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"\b[a-z0-9]{2,}\b", text)
        if word not in _IMPORTANT_STOPWORDS
    ]


def get_uncovered_text(normalized_text: str, commands: list[NormalizedCommand]) -> str:
    """Remove matched raw fragments from text and return the remaining words."""

    uncovered = f" {normalized_text} "
    for command in commands:
        raw_fragment = (command.raw_fragment or "").strip()
        if not raw_fragment:
            continue
        pattern = re.compile(rf"(?<!\w){re.escape(raw_fragment)}(?!\w)")
        uncovered = pattern.sub(" ", uncovered, count=1)
    return re.sub(r"\s+", " ", uncovered).strip()


def _coverage_score(normalized_text: str, commands: list[NormalizedCommand]) -> float:
    words = re.findall(r"\b[a-z0-9]+\b", normalized_text)
    if not words:
        return 1.0
    raw_fragments = [command.raw_fragment for command in commands if command.raw_fragment]
    if not raw_fragments:
        return 0.5 if commands else 0.0

    covered_words = len(words) - len(re.findall(r"\b[a-z0-9]+\b", get_uncovered_text(normalized_text, commands)))
    return max(0.0, min(1.0, covered_words / len(words)))


def check_command_completeness(
    normalized_text: str,
    commands: list[NormalizedCommand],
) -> CompletenessResult:
    """Detect whether important user intent remains unresolved."""

    coverage_score = _coverage_score(normalized_text, commands)
    if not commands:
        return CompletenessResult(
            is_complete=False,
            should_call_llm=True,
            reason="no_commands",
            unresolved_intents=["command"],
            coverage_score=coverage_score,
        )

    names = _command_names(commands)
    if CommandName.UNKNOWN in names:
        return CompletenessResult(
            is_complete=False,
            should_call_llm=True,
            reason="unknown_command",
            unresolved_intents=["unknown_command"],
            coverage_score=coverage_score,
        )

    unresolved_intents: list[str] = []
    reason: Optional[str] = None

    if (
        CommandName.SELECT_MONITOR in names
        and CommandName.SET_SIZE not in names
        and _has_absolute_size_intent(normalized_text)
    ):
        unresolved_intents.append("set_size")
        reason = "explicit_size_intent_missing_set_size"

    if (
        CommandName.INCREASE_SIZE not in names
        and _INCREASE_INTENT_PATTERN.search(normalized_text)
    ):
        unresolved_intents.append("increase_size")
        reason = reason or "increase_size_intent_missing_command"

    if (
        CommandName.DECREASE_SIZE not in names
        and _DECREASE_INTENT_PATTERN.search(normalized_text)
    ):
        unresolved_intents.append("decrease_size")
        reason = reason or "decrease_size_intent_missing_command"

    for movement_command, pattern in _DIRECTION_PATTERNS.items():
        if movement_command not in names and pattern.search(normalized_text):
            unresolved_intents.append(movement_command.value.lower())
            reason = reason or "movement_intent_missing_command"

    uncovered_words = _important_words(get_uncovered_text(normalized_text, commands))
    if uncovered_words and not unresolved_intents:
        unresolved_intents.append("uncovered_text")
        reason = "important_text_uncovered"

    should_call_llm = bool(unresolved_intents)
    return CompletenessResult(
        is_complete=not should_call_llm,
        should_call_llm=should_call_llm,
        reason=reason,
        unresolved_intents=unresolved_intents,
        coverage_score=coverage_score,
    )
