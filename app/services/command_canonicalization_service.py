"""Canonicalize LLM commands into app-compatible command sequences."""

from __future__ import annotations

from app.schemas import CommandName, MatchMethod, NormalizedCommand


def _command_key(command: NormalizedCommand) -> tuple:
    return (
        command.command,
        command.monitor,
        command.layout,
        command.size_inches,
        command.value,
    )


def _select_monitor_command(
    monitor: int,
    source: NormalizedCommand,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=CommandName.SELECT_MONITOR,
        confidence=source.confidence,
        method=source.method if source.method else MatchMethod.llm,
        monitor=monitor,
        raw_fragment=f"monitor {monitor}",
    )


def _copy_without_monitor(command: NormalizedCommand) -> NormalizedCommand:
    return NormalizedCommand(
        command=command.command,
        confidence=command.confidence,
        method=command.method,
        monitor=None,
        layout=command.layout,
        size_inches=command.size_inches,
        value=command.value,
        raw_fragment=command.raw_fragment,
    )


def _append_once(
    commands: list[NormalizedCommand],
    command: NormalizedCommand,
    seen: set[tuple],
) -> None:
    key = _command_key(command)
    if key in seen:
        return
    commands.append(command)
    seen.add(key)


def canonicalize_commands(
    commands: list[NormalizedCommand],
) -> list[NormalizedCommand]:
    """Convert monitor-scoped action commands into SELECT_MONITOR + action.

    LLMs sometimes attach ``monitor`` directly to action commands, for example
    ``SET_SIZE monitor=2 size_inches=75``. The app runtime expects monitor
    selection as a separate command, so this function extracts the monitor into
    ``SELECT_MONITOR`` and removes it from the original action command.
    """

    existing_monitors = {
        command.monitor
        for command in commands
        if command.command == CommandName.SELECT_MONITOR and command.monitor is not None
    }
    created_selects: list[NormalizedCommand] = []
    actions: list[NormalizedCommand] = []

    for command in commands:
        if command.command == CommandName.SELECT_MONITOR:
            actions.append(command)
            continue

        if command.command == CommandName.UNKNOWN:
            actions.append(command)
            continue

        if command.monitor is None:
            actions.append(command)
            continue

        monitor = command.monitor
        if monitor not in existing_monitors:
            created_selects.append(_select_monitor_command(monitor, command))
            existing_monitors.add(monitor)
        actions.append(_copy_without_monitor(command))

    ordered: list[NormalizedCommand] = []
    seen: set[tuple] = set()

    for command in actions:
        if command.command == CommandName.SELECT_MONITOR:
            _append_once(ordered, command, seen)

    for command in created_selects:
        _append_once(ordered, command, seen)

    for command in actions:
        if command.command != CommandName.SELECT_MONITOR:
            _append_once(ordered, command, seen)

    return ordered
