"""Domain-specific corrections for common ASR/Whisper transcription errors."""

from __future__ import annotations

import re


_SPACES_PATTERN = re.compile(r"\s+")

_CORRECTIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{re.escape(source)}\b"), target)
    for source, target in (
        ("pantaya", "pantalla"),
        ("pantaia", "pantalla"),
        ("pantalia", "pantalla"),
        ("pantalla pantalla", "pantalla"),
        ("monito", "monitor"),
        ("monitr", "monitor"),
        ("moniter", "monitor"),
        ("dereca", "derecha"),
        ("dereha", "derecha"),
        ("derecha derecha", "derecha"),
        ("izquerda", "izquierda"),
        ("isquierda", "izquierda"),
        ("esquierda", "izquierda"),
        ("licuada", "izquierda"),
        ("pulada", "pulgada"),
        ("puladas", "pulgadas"),
        ("pulgadaa", "pulgada"),
        ("a leja", "aleja"),
        ("a lejar", "alejar"),
        ("a lejos", "aleja"),
        ("al eja", "aleja"),
        ("ale j a", "aleja"),
        ("a cerca", "acerca"),
        ("a cercar", "acercar"),
        ("aleja lo", "alejalo"),
        ("acerca lo", "acercalo"),
        ("muevelo", "mueve"),
        ("muevela", "mueve"),
        ("mueveme", "mueve"),
        ("subele", "sube"),
        ("bajale", "baja"),
        ("dejalo", "deja"),
        ("ponla", "pon"),
        ("ponlo", "pon"),
        ("coja", "selecciona"),
        ("coge", "selecciona"),
        ("agarra", "selecciona"),
        ("toma", "selecciona"),
    )
)


def apply_asr_corrections(text: str) -> str:
    """Apply conservative voice-command domain corrections to normalized text."""

    corrected = text
    for pattern, replacement in _CORRECTIONS:
        corrected = pattern.sub(replacement, corrected)

    return _SPACES_PATTERN.sub(" ", corrected).strip()
