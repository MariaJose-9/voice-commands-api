"""Text preprocessing utilities."""

from __future__ import annotations

import re
import unicodedata

from app.asr_corrections import apply_asr_corrections


_QUOTE_TRANSLATION = str.maketrans(
    {
        "“": '"',
        "”": '"',
        "„": '"',
        "‟": '"',
        "’": "'",
        "‘": "'",
        "‚": "'",
        "`": "'",
    }
)

_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9\s,;]+")
_SPACES_PATTERN = re.compile(r"\s+")


def _strip_accents(text: str) -> str:
    """Return text without accent marks while preserving base characters."""

    normalized = unicodedata.normalize("NFKD", text)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def normalize_text(text: str) -> str:
    """Normalize transcribed command text for downstream matching.

    The function lowercases the input, normalizes quote variants, removes
    accents, keeps digits, strips unnecessary punctuation, and collapses
    duplicate whitespace.
    """

    normalized = text.translate(_QUOTE_TRANSLATION).lower()
    normalized = _strip_accents(normalized)
    normalized = apply_asr_corrections(normalized)
    normalized = normalized.replace("#", " ")
    normalized = _NON_ALNUM_PATTERN.sub(" ", normalized)
    normalized = _SPACES_PATTERN.sub(" ", normalized).strip()
    return normalized
