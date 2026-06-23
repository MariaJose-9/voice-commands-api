"""Entity extraction helpers."""

from __future__ import annotations

import re
from typing import Pattern


VALID_SIZES = {55, 65, 75, 95, 120}
_MONITOR_ALIASES = r"(?:monitor|monito|monitr|moniter|screen|pantalla)"

_MONITOR_PATTERNS: list[tuple[Pattern[str], int]] = [
    (re.compile(rf"\b{_MONITOR_ALIASES}\s+(?:one|1|uno)\b"), 1),
    (re.compile(r"\b(?:first|primer)\s+monitor\b"), 1),
    (re.compile(rf"\b{_MONITOR_ALIASES}\s+(?:two|2|dos)\b"), 2),
    (re.compile(r"\b(?:second|segundo)\s+monitor\b"), 2),
]

_LAYOUT_PATTERNS: list[tuple[Pattern[str], int]] = [
    (re.compile(r"\blayout\s+(?:one|1|uno)\b"), 1),
    (re.compile(r"\b(?:first|primer)\s+layout\b"), 1),
    (re.compile(r"\blayout\s+(?:two|2|dos)\b"), 2),
    (re.compile(r"\b(?:second|segundo)\s+layout\b"), 2),
]

_SIZE_PATTERNS: list[Pattern[str]] = [
    re.compile(r"\b(55|65|75|95|120)\s*inch(?:es)?\b"),
    re.compile(r"\b(55|65|75|95|120)\s*pulgadas\b"),
    re.compile(r"\b(?:tamano|tamaño)\s+(55|65|75|95|120)\b"),
    re.compile(r"\bset\s+(55|65|75|95|120)\s*inch(?:es)?\b"),
    re.compile(r"\bponlo\s+en\s+(55|65|75|95|120)\s*pulgadas\b"),
]

_STOP_PATTERN = re.compile(r"\b(?:stop|detener|parar|cancelar)\b")
_STREAM_PATTERN = re.compile(
    r"\b(?:stream|streaming|transmision|transmitir)\b"
)
_FOLLOW_PATTERN = re.compile(
    r"\b(?:follow\s+me|sigueme|seguirme|seguimiento)\b"
)


def _extract_value(
    text: str, patterns: list[tuple[Pattern[str], int]]
) -> int | None:
    """Return the first matching integer value for the given alias patterns."""

    for pattern, value in patterns:
        if pattern.search(text):
            return value
    return None


def _extract_size(text: str) -> int | None:
    """Return the first supported size detected in text."""

    for pattern in _SIZE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue

        size = int(match.group(1))
        if size in VALID_SIZES:
            return size

    return None


def extract_entities(normalized_text: str) -> dict:
    """Extract monitor, layout, size, and control flags from normalized text."""

    return {
        "monitor": _extract_value(normalized_text, _MONITOR_PATTERNS),
        "layout": _extract_value(normalized_text, _LAYOUT_PATTERNS),
        "size_inches": _extract_size(normalized_text),
        "flags": {
            "has_stop": bool(_STOP_PATTERN.search(normalized_text)),
            "has_stream": bool(_STREAM_PATTERN.search(normalized_text)),
            "has_follow": bool(_FOLLOW_PATTERN.search(normalized_text)),
        },
    }
