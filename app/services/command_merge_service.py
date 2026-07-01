"""Merge base normalization results with LLM command interpretations."""

from __future__ import annotations

from typing import Optional

from app import config
from app.multi_command import deduplicate_commands
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services import runtime_settings_service
from app.services.completeness_checker import check_command_completeness
from app.services.command_dedup_service import get_command_semantic_key


_MOVEMENT_COMMANDS = {
    CommandName.MOVE_LEFT,
    CommandName.MOVE_RIGHT,
    CommandName.MOVE_UP,
    CommandName.MOVE_DOWN,
}
_SIZE_COMMANDS = {
    CommandName.SET_SIZE,
    CommandName.ZOOM_IN,
    CommandName.ZOOM_OUT,
    CommandName.INCREASE_SIZE,
    CommandName.DECREASE_SIZE,
}
_UI_STREAM_COMMANDS = {
    CommandName.SHOW_AITROL,
    CommandName.CLOSE_AITROL,
    CommandName.SHOW_VOICE_COMMANDS,
    CommandName.CLOSE_VOICE_COMMANDS,
    CommandName.OPEN_SETTINGS,
    CommandName.CAPTURE,
    CommandName.START_STREAM,
    CommandName.START_RECORDING,
    CommandName.STOP_STREAM,
    CommandName.STOP_ACTIVE,
    CommandName.FOLLOW_ME,
    CommandName.STOP_FOLLOW_ME,
    CommandName.RECENTER_OBJECTS,
    CommandName.RESET_POSITION,
}
METHOD_PRIORITY = {
    "entity_rule": 100,
    "exact_rule": 90,
    "llm": 80,
    "semantic": 70,
    "fuzzy": 60,
    "unknown": 0,
}


def _has_useful_commands(response: NormalizeResponse) -> bool:
    return bool(response.commands) and all(
        command.command != CommandName.UNKNOWN for command in response.commands
    )


def _command_key(command: NormalizedCommand) -> tuple:
    return (
        command.command,
        command.monitor,
        command.layout,
        command.size_inches,
        command.value,
    )


def _valid_commands(commands: list[NormalizedCommand]) -> list[NormalizedCommand]:
    return [command for command in commands if isinstance(command.command, CommandName)]


def _command_names(commands: list[NormalizedCommand]) -> set[CommandName]:
    return {command.command for command in commands}


def _method_priority(command: NormalizedCommand) -> int:
    method = command.method.value if isinstance(command.method, MatchMethod) else str(command.method)
    return METHOD_PRIORITY.get(method, 0)


def choose_better_command(
    a: NormalizedCommand,
    b: NormalizedCommand,
) -> NormalizedCommand:
    """Choose the better command for the same semantic key."""

    a_priority = _method_priority(a)
    b_priority = _method_priority(b)
    if a_priority != b_priority:
        return a if a_priority > b_priority else b

    if a.confidence != b.confidence:
        return a if a.confidence > b.confidence else b

    return a


def deduplicate_commands_semantically(
    commands: list[NormalizedCommand],
) -> list[NormalizedCommand]:
    """Deduplicate commands by meaning while preserving first-key order."""

    by_key: dict[tuple, NormalizedCommand] = {}
    key_order: list[tuple] = []
    for command in _valid_commands(commands):
        key = get_command_semantic_key(command)
        if key not in by_key:
            by_key[key] = command
            key_order.append(key)
            continue
        by_key[key] = choose_better_command(by_key[key], command)

    return [by_key[key] for key in key_order]


def _merge_preserving_missing(
    primary: list[NormalizedCommand],
    secondary: list[NormalizedCommand],
) -> list[NormalizedCommand]:
    merged = list(_valid_commands(primary))
    seen = {_command_key(command) for command in merged}
    for command in _valid_commands(secondary):
        key = _command_key(command)
        if key in seen:
            continue
        merged.append(command)
        seen.add(key)
    return merged


def _sort_logically(commands: list[NormalizedCommand]) -> list[NormalizedCommand]:
    indexed_commands = list(enumerate(commands))

    def sort_key(item: tuple[int, NormalizedCommand]) -> tuple[int, int]:
        original_index, command = item
        if command.command == CommandName.SELECT_MONITOR:
            group = 0
        elif command.command == CommandName.SET_LAYOUT:
            group = 1
        elif command.command in _MOVEMENT_COMMANDS:
            group = 2
        elif command.command in _SIZE_COMMANDS:
            group = 3
        elif command.command in _UI_STREAM_COMMANDS:
            group = 4
        elif command.command == CommandName.UNKNOWN:
            group = 9
        else:
            group = 5
        return (group, original_index)

    return [command for _, command in sorted(indexed_commands, key=sort_key)]


def _accept_threshold() -> float:
    return runtime_settings_service.get_runtime_float_setting(
        "LLM_ACCEPT_THRESHOLD",
        config.LLM_ACCEPT_THRESHOLD,
    )


def _needs_confirmation(commands: list[NormalizedCommand]) -> bool:
    threshold = _accept_threshold()
    return any(command.command == CommandName.UNKNOWN for command in commands) or any(
        command.confidence < threshold for command in commands
    )


def _sorted_values(values: set[int]) -> list[int]:
    return sorted(value for value in values if value is not None)


def detect_command_conflicts(commands: list[NormalizedCommand]) -> list[dict]:
    """Return incompatibilities present in a command list."""

    conflicts: list[dict] = []

    set_sizes = {
        command.size_inches
        for command in commands
        if command.command == CommandName.SET_SIZE and command.size_inches is not None
    }
    if len(set_sizes) > 1:
        conflicts.append(
            {
                "type": "set_size_conflict",
                "values": _sorted_values(set_sizes),
                "message": "Conflicting SET_SIZE commands detected",
            }
        )

    monitors = {
        command.monitor
        for command in commands
        if command.command == CommandName.SELECT_MONITOR and command.monitor is not None
    }
    if len(monitors) > 1:
        conflicts.append(
            {
                "type": "select_monitor_conflict",
                "values": _sorted_values(monitors),
                "message": "Conflicting SELECT_MONITOR commands detected",
            }
        )

    layouts = {
        command.layout
        for command in commands
        if command.command == CommandName.SET_LAYOUT and command.layout is not None
    }
    if len(layouts) > 1:
        conflicts.append(
            {
                "type": "set_layout_conflict",
                "values": _sorted_values(layouts),
                "message": "Conflicting SET_LAYOUT commands detected",
            }
        )

    names = _command_names(commands)
    if {CommandName.MOVE_LEFT, CommandName.MOVE_RIGHT}.issubset(names):
        conflicts.append(
            {
                "type": "movement_conflict",
                "values": ["MOVE_LEFT", "MOVE_RIGHT"],
                "message": "Conflicting movement commands detected",
            }
        )
    if {CommandName.MOVE_UP, CommandName.MOVE_DOWN}.issubset(names):
        conflicts.append(
            {
                "type": "movement_conflict",
                "values": ["MOVE_UP", "MOVE_DOWN"],
                "message": "Conflicting movement commands detected",
            }
        )

    return conflicts


def _choose_set_size_conflict_winner(
    commands: list[NormalizedCommand],
    *,
    raw_text: str,
    normalized_text: str,
) -> NormalizedCommand:
    text = f"{raw_text} {normalized_text}".lower()
    entity_candidates = [
        command
        for command in commands
        if (
            command.method == MatchMethod.entity_rule
            and command.size_inches is not None
            and str(command.size_inches) in text
        )
    ]
    candidates = entity_candidates or commands
    best = candidates[0]
    for command in candidates[1:]:
        best = choose_better_command(best, command)
    return best


def _resolve_set_size_conflicts(
    commands: list[NormalizedCommand],
    *,
    raw_text: str,
    normalized_text: str,
) -> list[NormalizedCommand]:
    set_size_commands = [
        command
        for command in commands
        if command.command == CommandName.SET_SIZE and command.size_inches is not None
    ]
    size_values = {command.size_inches for command in set_size_commands}
    if len(size_values) <= 1:
        return commands

    best = _choose_set_size_conflict_winner(
        set_size_commands,
        raw_text=raw_text,
        normalized_text=normalized_text,
    )

    resolved: list[NormalizedCommand] = []
    best_inserted = False
    for command in commands:
        if command.command == CommandName.SET_SIZE and command.size_inches in size_values:
            if not best_inserted:
                resolved.append(best)
                best_inserted = True
            continue
        resolved.append(command)

    return resolved


def _conflict_message(conflicts: list[dict]) -> Optional[str]:
    if not conflicts:
        return None
    summaries = []
    for conflict in conflicts:
        values = ", ".join(str(value) for value in conflict.get("values", []))
        summaries.append(f"{conflict['message']}: {values}")
    return " ".join(summaries)


def merge_command_results(
    base_response: NormalizeResponse,
    llm_response: Optional[NormalizeResponse],
    prefer_llm_on_incomplete: bool = True,
    normalized_text: Optional[str] = None,
    raw_text: Optional[str] = None,
) -> NormalizeResponse:
    """Combine base parser output and LLM output without duplicating commands."""

    if llm_response is None:
        return base_response

    base_useful = _has_useful_commands(base_response)
    llm_useful = _has_useful_commands(llm_response)
    if not llm_useful:
        return base_response

    completeness = check_command_completeness(
        base_response.normalized_text,
        base_response.commands,
    )
    used_llm = False

    if not base_useful:
        merged_commands = list(llm_response.commands)
        used_llm = True
    elif prefer_llm_on_incomplete and not completeness.is_complete:
        merged_commands = _merge_preserving_missing(
            llm_response.commands,
            base_response.commands,
        )
        used_llm = True
    else:
        merged_commands = _merge_preserving_missing(
            base_response.commands,
            llm_response.commands,
        )
        used_llm = bool(llm_response.commands)

    merged_commands = deduplicate_commands_semantically(deduplicate_commands(merged_commands))
    effective_raw_text = raw_text or base_response.raw_text or llm_response.raw_text
    effective_normalized_text = (
        normalized_text
        or base_response.normalized_text
        or llm_response.normalized_text
    )
    conflicts = detect_command_conflicts(merged_commands)
    merged_commands = _resolve_set_size_conflicts(
        merged_commands,
        raw_text=effective_raw_text,
        normalized_text=effective_normalized_text,
    )
    merged_commands = _sort_logically(merged_commands)
    conflict_message = _conflict_message(conflicts)
    message = base_response.message
    if used_llm:
        message = (
            "Completed with LLM"
            if not message
            else f"{message} Completed with LLM"
        )
    if conflict_message:
        message = conflict_message if not message else f"{message} {conflict_message}"

    return NormalizeResponse(
        ok=all(command.command != CommandName.UNKNOWN for command in merged_commands),
        raw_text=base_response.raw_text,
        normalized_text=base_response.normalized_text,
        language=base_response.language or llm_response.language,
        commands=merged_commands,
        needs_confirmation=bool(conflict_message) or _needs_confirmation(merged_commands),
        message=message,
    )
