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
    "configura",
    "de",
    "del",
    "el",
    "en",
    "este",
    "esté",
    "it",
    "la",
    "las",
    "lo",
    "los",
    "me",
    "necesito",
    "please",
    "pon",
    "poner",
    "por",
    "favor",
    "que",
    "quiero",
    "the",
    "to",
    "un",
    "una",
    "uno",
    "y",
}

_MONITOR_INTENT_PATTERN = re.compile(
    r"\b(monitor|pantalla|screen|display)\s*(1|2|uno|una|dos)\b|"
    r"\b(primera|segunda)\s+pantalla\b|"
    r"\b(primer|segundo)\s+monitor\b"
)
_SIZE_INTENT_PATTERN = re.compile(
    r"\b("
    r"redimensiona|redimensionar|resize|"
    r"cambia\s+tamano|cambia\s+tamaño|cambiar\s+tamano|cambiar\s+tamaño|"
    r"ajusta\s+tamano|ajusta\s+tamaño|tamano|tamaño|pulgadas?|inches?|"
    r"escala|escalar|dimensiona"
    r")\b"
)
_SIZE_NUMBER_PATTERN = re.compile(r"\b\d{2,3}\b")
_INCREASE_INTENT_PATTERN = re.compile(
    r"\b("
    r"grande|mas\s+grande|más\s+grande|agranda|aumentar|aumenta|"
    r"sube\s+tamano|sube\s+tamaño|subele|bigger|larger|increase"
    r")\b"
)
_DECREASE_INTENT_PATTERN = re.compile(
    r"\b("
    r"pequeno|pequeño|chico|mas\s+pequeno|más\s+pequeño|reduce|"
    r"reducir|achica|baja\s+tamano|baja\s+tamaño|smaller|decrease"
    r")\b"
)
_DIRECTION_PATTERNS = {
    CommandName.MOVE_LEFT: re.compile(r"\b(izquierda|left)\b"),
    CommandName.MOVE_RIGHT: re.compile(r"\b(derecha|right)\b"),
    CommandName.MOVE_UP: re.compile(r"\b(arriba|up)\b"),
    CommandName.MOVE_DOWN: re.compile(r"\b(abajo|down)\b"),
}
_ZOOM_INTENT_PATTERN = re.compile(
    r"\b(zoom|acerca|acercar|acercalo|aleja|alejar|alejalo)\b"
)
_LAYOUT_INTENT_PATTERN = re.compile(
    r"\b(layout|vista|diseno|diseño)\s*(1|2|uno|dos)?\b"
)
_UI_INTENT_PATTERN = re.compile(
    r"\b(aitrol|settings|ajustes|configuracion|configuración|"
    r"comandos\s+de\s+voz|voice\s+commands?)\b"
)
_STREAM_INTENT_PATTERN = re.compile(
    r"\b(stream|streaming|transmision|transmisión|transmitir|record|"
    r"recording|grabar|detener|parar|cancelar|stop)\b"
)
_CAPTURE_INTENT_PATTERN = re.compile(r"\b(capture|screenshot|captura|pantallazo)\b")

_INTENT_WORDS = {
    "monitor_selection": {
        "monitor",
        "pantalla",
        "screen",
        "display",
        "primera",
        "segunda",
        "primer",
        "segundo",
        "numero",
        "número",
        "uno",
        "una",
        "dos",
        "1",
        "2",
    },
    "set_size": {
        "redimensiona",
        "redimensionar",
        "resize",
        "cambia",
        "cambiar",
        "ajusta",
        "tamano",
        "tamaño",
        "pulgada",
        "pulgadas",
        "inch",
        "inches",
        "escala",
        "escalar",
        "dimensiona",
    },
    "increase_size": {
        "grande",
        "mas",
        "más",
        "agranda",
        "aumentar",
        "aumenta",
        "sube",
        "subele",
        "bigger",
        "larger",
        "increase",
    },
    "decrease_size": {
        "pequeno",
        "pequeño",
        "chico",
        "reduce",
        "reducir",
        "achica",
        "baja",
        "smaller",
        "decrease",
    },
    "movement": {
        "izquierda",
        "derecha",
        "arriba",
        "abajo",
        "left",
        "right",
        "up",
        "down",
        "mueve",
        "mover",
        "lleva",
        "desplaza",
    },
    "zoom": {
        "zoom",
        "acerca",
        "acercar",
        "acercalo",
        "aleja",
        "alejar",
        "alejalo",
    },
    "layout": {"layout", "vista", "diseno", "diseño"},
    "ui": {
        "aitrol",
        "settings",
        "ajustes",
        "configuracion",
        "configuración",
        "comandos",
        "voz",
        "voice",
        "commands",
    },
    "stream": {
        "stream",
        "streaming",
        "transmision",
        "transmisión",
        "transmitir",
        "record",
        "recording",
        "grabar",
        "detener",
        "parar",
        "cancelar",
        "stop",
    },
    "capture": {"capture", "screenshot", "captura", "pantallazo"},
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


def _detect_present_intents(normalized_text: str) -> set[str]:
    intents: set[str] = set()
    if _MONITOR_INTENT_PATTERN.search(normalized_text):
        intents.add("monitor_selection")
    if _has_absolute_size_intent(normalized_text):
        intents.add("set_size")
    if _INCREASE_INTENT_PATTERN.search(normalized_text):
        intents.add("increase_size")
    if _DECREASE_INTENT_PATTERN.search(normalized_text):
        intents.add("decrease_size")
    if any(pattern.search(normalized_text) for pattern in _DIRECTION_PATTERNS.values()):
        intents.add("movement")
    if _ZOOM_INTENT_PATTERN.search(normalized_text):
        intents.add("zoom")
    if _LAYOUT_INTENT_PATTERN.search(normalized_text):
        intents.add("layout")
    if _UI_INTENT_PATTERN.search(normalized_text):
        intents.add("ui")
    if _STREAM_INTENT_PATTERN.search(normalized_text):
        intents.add("stream")
    if _CAPTURE_INTENT_PATTERN.search(normalized_text):
        intents.add("capture")
    return intents


def _covered_intents(names: set[CommandName]) -> set[str]:
    covered: set[str] = set()
    if CommandName.SELECT_MONITOR in names:
        covered.add("monitor_selection")
    if CommandName.SET_SIZE in names:
        covered.add("set_size")
    if CommandName.INCREASE_SIZE in names:
        covered.add("increase_size")
    if CommandName.DECREASE_SIZE in names:
        covered.add("decrease_size")
    if names & {
        CommandName.MOVE_LEFT,
        CommandName.MOVE_RIGHT,
        CommandName.MOVE_UP,
        CommandName.MOVE_DOWN,
    }:
        covered.add("movement")
    if names & {CommandName.ZOOM_IN, CommandName.ZOOM_OUT}:
        covered.add("zoom")
    if CommandName.SET_LAYOUT in names:
        covered.add("layout")
    if names & {
        CommandName.SHOW_AITROL,
        CommandName.CLOSE_AITROL,
        CommandName.SHOW_VOICE_COMMANDS,
        CommandName.CLOSE_VOICE_COMMANDS,
        CommandName.OPEN_SETTINGS,
    }:
        covered.add("ui")
    if names & {
        CommandName.START_STREAM,
        CommandName.STOP_STREAM,
        CommandName.START_RECORDING,
        CommandName.STOP_ACTIVE,
    }:
        covered.add("stream")
    if CommandName.CAPTURE in names:
        covered.add("capture")
    return covered


def _important_words(text: str) -> list[str]:
    return [
        word
        for word in re.findall(r"\b[a-z0-9]{1,}\b", text)
        if word not in _IMPORTANT_STOPWORDS
    ]


def _filter_words_covered_by_intents(
    words: list[str],
    covered_intents: set[str],
) -> list[str]:
    covered_words: set[str] = set()
    for intent in covered_intents:
        covered_words.update(_INTENT_WORDS.get(intent, set()))

    filtered: list[str] = []
    for word in words:
        if word in covered_words:
            continue
        if word.isdigit() and (
            "set_size" in covered_intents or "monitor_selection" in covered_intents
        ):
            continue
        filtered.append(word)
    return filtered


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

    covered_words = len(words) - len(
        re.findall(r"\b[a-z0-9]+\b", get_uncovered_text(normalized_text, commands))
    )
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

    present_intents = _detect_present_intents(normalized_text)
    covered_intents = _covered_intents(names)
    missing_intents = present_intents - covered_intents

    unresolved_intents: list[str] = []
    reason: Optional[str] = None

    if "set_size" in missing_intents:
        unresolved_intents.append("set_size")
        reason = "explicit_size_intent_missing_set_size"

    if "increase_size" in missing_intents:
        unresolved_intents.append("increase_size")
        reason = reason or "increase_size_intent_missing_command"

    if "decrease_size" in missing_intents:
        unresolved_intents.append("decrease_size")
        reason = reason or "decrease_size_intent_missing_command"

    if "movement" in missing_intents:
        for movement_command, pattern in _DIRECTION_PATTERNS.items():
            if pattern.search(normalized_text):
                unresolved_intents.append(movement_command.value.lower())
                break
        reason = reason or "movement_intent_missing_command"

    for generic_intent in [
        "monitor_selection",
        "zoom",
        "layout",
        "ui",
        "stream",
        "capture",
    ]:
        if generic_intent in missing_intents:
            unresolved_intents.append(generic_intent)
            reason = reason or f"{generic_intent}_intent_missing_command"

    uncovered_words = _filter_words_covered_by_intents(
        _important_words(get_uncovered_text(normalized_text, commands)),
        covered_intents,
    )
    if uncovered_words and not unresolved_intents:
        unresolved_intents.append("uncovered_text")
        reason = "important_text_uncovered"

    should_call_llm = bool(unresolved_intents)
    if not should_call_llm:
        coverage_score = max(coverage_score, 0.95)

    return CompletenessResult(
        is_complete=not should_call_llm,
        should_call_llm=should_call_llm,
        reason=reason,
        unresolved_intents=unresolved_intents,
        coverage_score=coverage_score,
    )
