from __future__ import annotations

from app.schemas import CommandName, MatchMethod, NormalizedCommand
from app.services.command_dedup_service import get_command_semantic_key


def _command(
    command: CommandName,
    *,
    monitor: int | None = None,
    layout: int | None = None,
    size_inches: int | None = None,
    raw_fragment: str | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=1.0,
        method=MatchMethod.entity_rule,
        monitor=monitor,
        layout=layout,
        size_inches=size_inches,
        raw_fragment=raw_fragment,
    )


def test_set_size_key_ignores_monitor() -> None:
    with_monitor = _command(CommandName.SET_SIZE, monitor=2, size_inches=75)
    without_monitor = _command(CommandName.SET_SIZE, size_inches=75)

    assert get_command_semantic_key(with_monitor) == get_command_semantic_key(
        without_monitor
    )
    assert get_command_semantic_key(with_monitor) == ("SET_SIZE", 75)


def test_select_monitor_keys_include_monitor() -> None:
    monitor_one = _command(CommandName.SELECT_MONITOR, monitor=1)
    monitor_two = _command(CommandName.SELECT_MONITOR, monitor=2)

    assert get_command_semantic_key(monitor_one) == ("SELECT_MONITOR", 1)
    assert get_command_semantic_key(monitor_two) == ("SELECT_MONITOR", 2)
    assert get_command_semantic_key(monitor_one) != get_command_semantic_key(
        monitor_two
    )


def test_move_right_key_is_always_same() -> None:
    first = _command(CommandName.MOVE_RIGHT)
    second = _command(CommandName.MOVE_RIGHT, monitor=2, raw_fragment="derecha")

    assert get_command_semantic_key(first) == ("MOVE_RIGHT",)
    assert get_command_semantic_key(first) == get_command_semantic_key(second)


def test_set_layout_keys_include_layout() -> None:
    layout_one = _command(CommandName.SET_LAYOUT, layout=1)
    layout_two = _command(CommandName.SET_LAYOUT, layout=2)

    assert get_command_semantic_key(layout_one) == ("SET_LAYOUT", 1)
    assert get_command_semantic_key(layout_two) == ("SET_LAYOUT", 2)
    assert get_command_semantic_key(layout_one) != get_command_semantic_key(layout_two)


def test_unknown_key_uses_raw_fragment() -> None:
    unknown = _command(CommandName.UNKNOWN, raw_fragment="unparsed text")

    assert get_command_semantic_key(unknown) == ("UNKNOWN", "unparsed text")
