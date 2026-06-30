"""Entity extraction helpers."""

from __future__ import annotations

import re
from typing import Pattern

from app.services.entity_catalog_service import get_active_entities

_STOP_PATTERN = re.compile(r"\b(?:stop|detener|parar|cancelar)\b")
_STREAM_PATTERN = re.compile(
    r"\b(?:stream|streaming|transmision|transmitir)\b"
)
_FOLLOW_PATTERN = re.compile(
    r"\b(?:follow\s+me|sigueme|seguirme|seguimiento)\b"
)
_SPOKEN_SIZE_VALUES: dict[str, int] = {
    "cincuenta y cinco": 55,
    "cincuenta cinco": 55,
    "sesenta y cinco": 65,
    "sesenta cinco": 65,
    "setenta y cinco": 75,
    "setenta cinco": 75,
    "noventa y cinco": 95,
    "noventa cinco": 95,
    "ciento veinte": 120,
    "cien veinte": 120,
    "fifty five": 55,
    "sixty five": 65,
    "seventy five": 75,
    "ninety five": 95,
    "one hundred twenty": 120,
    "one twenty": 120,
}


def _extract_alias_value(text: str, aliases_by_value: dict[str, list[str]]) -> int | None:
    """Return the first matching integer value for the given alias map."""

    candidates: list[tuple[str, str]] = []
    for value, aliases in aliases_by_value.items():
        for alias in aliases:
            candidates.append((alias, value))

    candidates.sort(key=lambda item: (-len(item[0]), item[0]))
    for alias, value in candidates:
        if re.search(rf"\b{re.escape(alias)}\b", text):
            return int(value)
    return None


def _extract_size(text: str, aliases_by_value: dict[str, list[str]]) -> int | None:
    """Return the first supported size detected in text."""

    alias_value = _extract_alias_value(text, aliases_by_value)
    if alias_value is not None:
        return alias_value

    valid_sizes = sorted(
        [int(value) for value in aliases_by_value.keys() if str(value).isdigit()],
        key=int,
    )
    if not valid_sizes:
        return None

    sizes_group = "|".join(re.escape(str(size)) for size in valid_sizes)
    spanish_size_unit = r"(?:pulgada|pulgadas|pulada|puladas)"
    english_size_unit = r"inch(?:es)?"
    patterns: list[Pattern[str]] = [
        re.compile(rf"\b({sizes_group})\s*inch(?:es)?\b"),
        re.compile(rf"\b({sizes_group})\s*{spanish_size_unit}\b"),
        re.compile(rf"\btamano(?:\s+de)?\s+({sizes_group})\b"),
        re.compile(rf"\bset\s+({sizes_group})\s*inch(?:es)?\b"),
        re.compile(rf"\bpon\s+.*?\ben\s+({sizes_group})(?:\s*{spanish_size_unit})?\b"),
        re.compile(rf"\b(?:a|en|de)\s+({sizes_group})\b"),
        re.compile(rf"\b(?:pantalla|monitor)\s+(?:de\s+)?({sizes_group})\b"),
        re.compile(rf"\bset\s+(?:screen|monitor)(?:\s+\w+)?\s+to\s+({sizes_group})\b"),
    ]

    for pattern in patterns:
        match = pattern.search(text)
        if match:
            return int(match.group(1))

    spoken_patterns: list[tuple[Pattern[str], int]] = []
    for phrase, size in sorted(
        _SPOKEN_SIZE_VALUES.items(),
        key=lambda item: (-len(item[0]), item[0]),
    ):
        if size not in valid_sizes:
            continue
        spoken_patterns.extend(
            [
                (
                    re.compile(
                        rf"\b{re.escape(phrase)}\s*(?:{spanish_size_unit}|{english_size_unit})?\b"
                    ),
                    size,
                ),
                (
                    re.compile(
                        rf"\b(?:a|en|de|to)\s+{re.escape(phrase)}(?:\s*(?:{spanish_size_unit}|{english_size_unit}))?\b"
                    ),
                    size,
                ),
                (
                    re.compile(
                        rf"\b(?:tamano|size)(?:\s+de)?\s+{re.escape(phrase)}\b"
                    ),
                    size,
                ),
            ]
        )

    for pattern, size in spoken_patterns:
        if pattern.search(text):
            return size

    return None


def extract_entities(normalized_text: str) -> dict:
    """Extract monitor, layout, size, and control flags from normalized text."""

    entities = get_active_entities()

    return {
        "monitor": _extract_alias_value(normalized_text, entities.get("monitor", {})),
        "layout": _extract_alias_value(normalized_text, entities.get("layout", {})),
        "size_inches": _extract_size(normalized_text, entities.get("size_inches", {})),
        "flags": {
            "has_stop": bool(_STOP_PATTERN.search(normalized_text)),
            "has_stream": bool(_STREAM_PATTERN.search(normalized_text)),
            "has_follow": bool(_FOLLOW_PATTERN.search(normalized_text)),
        },
    }
