"""Multi-command splitting and orchestration."""

from __future__ import annotations

import re

from app.schemas import CommandName, MatchMethod, NormalizedCommand


_PROTECTED_PHRASES = [
    "stop follow me",
    "follow me",
    "stop stream",
    "voice commands",
    "voice command",
    "recenter objects",
    "center objects",
    "reset position",
]
_PROTECTED_PREFIX = "__protected_"
_CONNECTOR_PATTERN = re.compile(
    r"\s*(?:,|;|\band\b|\bthen\b|\bafter that\b|\by\b|\bluego\b|\bdespues\b)\s*"
)
_SUPPRESSION_RULES: dict[CommandName, set[CommandName]] = {
    CommandName.STOP_STREAM: {CommandName.STOP_ACTIVE},
    CommandName.STOP_FOLLOW_ME: {CommandName.FOLLOW_ME},
    CommandName.RECENTER_OBJECTS: {
        CommandName.MOVE_LEFT,
        CommandName.MOVE_RIGHT,
        CommandName.MOVE_UP,
        CommandName.MOVE_DOWN,
    },
}


def split_into_fragments(normalized_text: str) -> list[str]:
    """Split a normalized utterance into command fragments."""

    protected_text = normalized_text
    replacements: dict[str, str] = {}

    for index, phrase in enumerate(sorted(_PROTECTED_PHRASES, key=len, reverse=True)):
        placeholder = f"{_PROTECTED_PREFIX}{index}__"
        if phrase in protected_text:
            protected_text = protected_text.replace(phrase, placeholder)
            replacements[placeholder] = phrase

    fragments = []
    for fragment in _CONNECTOR_PATTERN.split(protected_text):
        cleaned = fragment.strip()
        if not cleaned:
            continue

        for placeholder, phrase in replacements.items():
            cleaned = cleaned.replace(placeholder, phrase)

        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        if cleaned:
            fragments.append(cleaned)

    return fragments


def _command_key(command: NormalizedCommand) -> tuple:
    """Return a stable deduplication key for a normalized command."""

    return (
        command.command,
        command.monitor,
        command.layout,
        command.size_inches,
        command.value,
    )


def deduplicate_commands(commands: list[NormalizedCommand]) -> list[NormalizedCommand]:
    """Remove duplicate or suppressed commands while preserving text order."""

    present_commands = {command.command for command in commands}
    suppressed_commands: set[CommandName] = set()
    for command_name in present_commands:
        suppressed_commands.update(_SUPPRESSION_RULES.get(command_name, set()))

    deduplicated: list[NormalizedCommand] = []
    seen_keys: set[tuple] = set()

    for command in commands:
        if command.command in suppressed_commands:
            continue

        key = _command_key(command)
        if key in seen_keys:
            continue

        deduplicated.append(command)
        seen_keys.add(key)

    return deduplicated
