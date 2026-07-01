from __future__ import annotations

from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services.command_merge_service import merge_command_results


def _command(
    command: CommandName,
    *,
    confidence: float = 0.95,
    monitor: int | None = None,
    layout: int | None = None,
    size_inches: int | None = None,
    raw_fragment: str | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=confidence,
        method=MatchMethod.llm if confidence != 1.0 else MatchMethod.entity_rule,
        monitor=monitor,
        layout=layout,
        size_inches=size_inches,
        raw_fragment=raw_fragment or command.value.lower(),
    )


def _response(
    commands: list[NormalizedCommand],
    *,
    raw_text: str = "monitor 1",
    normalized_text: str = "monitor 1",
    needs_confirmation: bool = False,
    message: str | None = None,
) -> NormalizeResponse:
    return NormalizeResponse(
        ok=all(command.command != CommandName.UNKNOWN for command in commands),
        raw_text=raw_text,
        normalized_text=normalized_text,
        language="es",
        commands=commands,
        needs_confirmation=needs_confirmation,
        message=message,
    )


def test_merge_base_monitor_with_llm_set_size() -> None:
    base = _response(
        [_command(CommandName.SELECT_MONITOR, confidence=1.0, monitor=1)],
        raw_text="redimensiona a 72 pulgadas el monitor 1",
        normalized_text="redimensiona a 72 pulgadas el monitor 1",
    )
    llm = _response(
        [_command(CommandName.SET_SIZE, size_inches=72)],
        raw_text=base.raw_text,
        normalized_text=base.normalized_text,
    )

    merged = merge_command_results(base, llm)

    assert [command.command for command in merged.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert merged.commands[0].monitor == 1
    assert merged.commands[1].size_inches == 72
    assert merged.message == "Completed with LLM"


def test_merge_deduplicates_select_monitor_from_llm() -> None:
    base = _response(
        [_command(CommandName.SELECT_MONITOR, confidence=1.0, monitor=1)],
        raw_text="redimensiona a 72 pulgadas el monitor 1",
        normalized_text="redimensiona a 72 pulgadas el monitor 1",
    )
    llm = _response(
        [
            _command(CommandName.SELECT_MONITOR, monitor=1),
            _command(CommandName.SET_SIZE, size_inches=72),
        ],
        raw_text=base.raw_text,
        normalized_text=base.normalized_text,
    )

    merged = merge_command_results(base, llm)

    assert [command.command for command in merged.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert len([command for command in merged.commands if command.command == CommandName.SELECT_MONITOR]) == 1


def test_merge_uses_llm_when_base_is_unknown() -> None:
    base = _response(
        [_command(CommandName.UNKNOWN, confidence=0.0)],
        raw_text="begin live",
        normalized_text="begin live",
        needs_confirmation=True,
    )
    llm = _response(
        [_command(CommandName.START_STREAM)],
        raw_text=base.raw_text,
        normalized_text=base.normalized_text,
    )

    merged = merge_command_results(base, llm)

    assert [command.command for command in merged.commands] == [CommandName.START_STREAM]
    assert merged.ok is True


def test_merge_returns_base_when_llm_is_none() -> None:
    base = _response([_command(CommandName.MOVE_LEFT)])

    merged = merge_command_results(base, None)

    assert merged is base


def test_merge_stop_stream_suppresses_stop_active() -> None:
    base = _response([_command(CommandName.STOP_ACTIVE)])
    llm = _response([_command(CommandName.STOP_STREAM)])

    merged = merge_command_results(base, llm)

    assert [command.command for command in merged.commands] == [CommandName.STOP_STREAM]


def test_merge_low_confidence_marks_needs_confirmation() -> None:
    base = _response([_command(CommandName.UNKNOWN, confidence=0.0)])
    llm = _response([_command(CommandName.MOVE_RIGHT, confidence=0.5)])

    merged = merge_command_results(base, llm)

    assert [command.command for command in merged.commands] == [CommandName.MOVE_RIGHT]
    assert merged.needs_confirmation is True
