from __future__ import annotations

from app.multi_command import deduplicate_commands, split_into_fragments
from app.schemas import CommandName, MatchMethod, NormalizedCommand


def _command(
    command: CommandName,
    *,
    monitor: int | None = None,
    layout: int | None = None,
    size_inches: int | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=1.0,
        method=MatchMethod.exact_rule,
        monitor=monitor,
        layout=layout,
        size_inches=size_inches,
    )


def test_split_into_fragments_english_connectors() -> None:
    fragments = split_into_fragments("select monitor one and zoom in")
    assert fragments == ["select monitor one", "zoom in"]


def test_split_into_fragments_mixed_separators() -> None:
    fragments = split_into_fragments("monitor two, move left and make it 65 inches")
    assert fragments == ["monitor two", "move left", "make it 65 inches"]


def test_split_into_fragments_spanish_connectors() -> None:
    fragments = split_into_fragments(
        "monitor dos, muevelo a la izquierda y ponlo en 65 pulgadas"
    )
    assert fragments == [
        "monitor dos",
        "muevelo a la izquierda",
        "ponlo en 65 pulgadas",
    ]


def test_split_into_fragments_handles_then_after_that() -> None:
    fragments = split_into_fragments("open aitrol then show voice commands after that reset position")
    assert fragments == ["open aitrol", "show voice commands", "reset position"]


def test_split_into_fragments_preserves_protected_phrases() -> None:
    fragments = split_into_fragments("stop stream and reset position")
    assert fragments == ["stop stream", "reset position"]


def test_split_into_fragments_handles_spanish_then_and_fillers() -> None:
    fragments = split_into_fragments(
        "pantalla 2 mueve la la derecha y luego las es en el tamano de 55 pulgadas"
    )
    assert fragments == [
        "pantalla 2 mueve la derecha",
        "en el tamano de 55 pulgadas",
    ]


def test_split_into_fragments_handles_entonces_connector() -> None:
    fragments = split_into_fragments("monitor dos entonces derecha despues en 65")
    assert fragments == ["monitor dos", "derecha", "en 65"]


def test_deduplicate_commands_removes_exact_duplicates() -> None:
    commands = [
        _command(CommandName.SELECT_MONITOR, monitor=1),
        _command(CommandName.SELECT_MONITOR, monitor=1),
        _command(CommandName.ZOOM_IN),
    ]
    result = deduplicate_commands(commands)
    assert [command.command for command in result] == [
        CommandName.SELECT_MONITOR,
        CommandName.ZOOM_IN,
    ]


def test_deduplicate_commands_keeps_same_command_with_different_params() -> None:
    commands = [
        _command(CommandName.SELECT_MONITOR, monitor=1),
        _command(CommandName.SELECT_MONITOR, monitor=2),
    ]
    result = deduplicate_commands(commands)
    assert [(command.command, command.monitor) for command in result] == [
        (CommandName.SELECT_MONITOR, 1),
        (CommandName.SELECT_MONITOR, 2),
    ]


def test_deduplicate_commands_suppresses_stop_active_when_stop_stream_exists() -> None:
    commands = [
        _command(CommandName.STOP_STREAM),
        _command(CommandName.STOP_ACTIVE),
        _command(CommandName.RESET_POSITION),
    ]
    result = deduplicate_commands(commands)
    assert [command.command for command in result] == [
        CommandName.STOP_STREAM,
        CommandName.RESET_POSITION,
    ]


def test_deduplicate_commands_suppresses_follow_me_when_stop_follow_me_exists() -> None:
    commands = [
        _command(CommandName.FOLLOW_ME),
        _command(CommandName.STOP_FOLLOW_ME),
    ]
    result = deduplicate_commands(commands)
    assert [command.command for command in result] == [CommandName.STOP_FOLLOW_ME]


def test_deduplicate_commands_suppresses_direction_when_recenter_exists() -> None:
    commands = [
        _command(CommandName.MOVE_LEFT),
        _command(CommandName.RECENTER_OBJECTS),
        _command(CommandName.MOVE_UP),
    ]
    result = deduplicate_commands(commands)
    assert [command.command for command in result] == [CommandName.RECENTER_OBJECTS]
