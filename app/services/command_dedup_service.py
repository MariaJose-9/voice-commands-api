"""Semantic deduplication helpers for normalized commands."""

from __future__ import annotations

from app.schemas import CommandName, NormalizedCommand


_SIMPLE_COMMANDS = {
    CommandName.MOVE_LEFT,
    CommandName.MOVE_RIGHT,
    CommandName.MOVE_UP,
    CommandName.MOVE_DOWN,
    CommandName.ZOOM_IN,
    CommandName.ZOOM_OUT,
    CommandName.INCREASE_SIZE,
    CommandName.DECREASE_SIZE,
    CommandName.FOLLOW_ME,
    CommandName.STOP_FOLLOW_ME,
    CommandName.RECENTER_OBJECTS,
    CommandName.RESET_POSITION,
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
}


def get_command_semantic_key(command: NormalizedCommand) -> tuple:
    """Return a meaning-based key for command deduplication."""

    if command.command == CommandName.SELECT_MONITOR:
        return (CommandName.SELECT_MONITOR.value, command.monitor)

    if command.command == CommandName.SET_SIZE:
        return (CommandName.SET_SIZE.value, command.size_inches)

    if command.command == CommandName.SET_LAYOUT:
        return (CommandName.SET_LAYOUT.value, command.layout)

    if command.command in _SIMPLE_COMMANDS:
        return (command.command.value,)

    if command.command == CommandName.UNKNOWN:
        return (
            CommandName.UNKNOWN.value,
            command.raw_fragment or command.value or "",
        )

    return (
        command.command.value,
        command.monitor,
        command.layout,
        command.size_inches,
        command.value,
    )
