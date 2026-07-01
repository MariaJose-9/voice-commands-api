from __future__ import annotations

from app.schemas import CommandName, MatchMethod, NormalizedCommand
from app.services.command_canonicalization_service import canonicalize_commands


def _command(
    command: CommandName,
    *,
    monitor: int | None = None,
    layout: int | None = None,
    size_inches: int | None = None,
    confidence: float = 0.9,
    raw_fragment: str | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=confidence,
        method=MatchMethod.llm,
        monitor=monitor,
        layout=layout,
        size_inches=size_inches,
        raw_fragment=raw_fragment or command.value.lower(),
    )


def test_set_size_with_monitor_becomes_select_monitor_plus_set_size() -> None:
    result = canonicalize_commands(
        [
            _command(
                CommandName.SET_SIZE,
                monitor=2,
                size_inches=75,
                raw_fragment="monitor 2 en 75 pulgadas",
            )
        ]
    )

    assert [command.command for command in result] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert result[0].monitor == 2
    assert result[0].method == MatchMethod.llm
    assert result[0].confidence == 0.9
    assert result[0].raw_fragment == "monitor 2"
    assert result[1].monitor is None
    assert result[1].size_inches == 75
    assert result[1].raw_fragment == "monitor 2 en 75 pulgadas"


def test_move_right_with_monitor_becomes_select_monitor_plus_move_right() -> None:
    result = canonicalize_commands(
        [_command(CommandName.MOVE_RIGHT, monitor=1, raw_fragment="monitor 1 derecha")]
    )

    assert [command.command for command in result] == [
        CommandName.SELECT_MONITOR,
        CommandName.MOVE_RIGHT,
    ]
    assert result[0].monitor == 1
    assert result[1].monitor is None


def test_existing_select_monitor_is_not_duplicated() -> None:
    result = canonicalize_commands(
        [
            _command(CommandName.SELECT_MONITOR, monitor=2, raw_fragment="monitor 2"),
            _command(CommandName.SET_SIZE, monitor=2, size_inches=75),
        ]
    )

    assert [command.command for command in result] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert result[0].monitor == 2
    assert result[1].monitor is None
    assert result[1].size_inches == 75


def test_set_size_without_monitor_stays_unchanged() -> None:
    original = _command(CommandName.SET_SIZE, size_inches=75)

    result = canonicalize_commands([original])

    assert result == [original]


def test_unknown_command_does_not_break() -> None:
    unknown = _command(CommandName.UNKNOWN, monitor=2, raw_fragment="unknown")

    result = canonicalize_commands([unknown])

    assert result == [unknown]
