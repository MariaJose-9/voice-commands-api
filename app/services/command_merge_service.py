"""Merge base normalization results with LLM command interpretations."""

from __future__ import annotations

from typing import Optional

from app import config
from app.multi_command import deduplicate_commands
from app.schemas import CommandName, NormalizeResponse, NormalizedCommand
from app.services import runtime_settings_service
from app.services.completeness_checker import check_command_completeness


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


def merge_command_results(
    base_response: NormalizeResponse,
    llm_response: Optional[NormalizeResponse],
    prefer_llm_on_incomplete: bool = True,
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

    merged_commands = _sort_logically(deduplicate_commands(merged_commands))
    message = base_response.message
    if used_llm:
        message = (
            "Completed with LLM"
            if not message
            else f"{message} Completed with LLM"
        )

    return NormalizeResponse(
        ok=all(command.command != CommandName.UNKNOWN for command in merged_commands),
        raw_text=base_response.raw_text,
        normalized_text=base_response.normalized_text,
        language=base_response.language or llm_response.language,
        commands=merged_commands,
        needs_confirmation=_needs_confirmation(merged_commands),
        message=message,
    )
