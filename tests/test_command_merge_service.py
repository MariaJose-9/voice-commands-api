from __future__ import annotations

from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services.command_merge_service import (
    choose_better_command,
    deduplicate_commands_semantically,
    detect_command_conflicts,
    merge_command_results,
)


def _command(
    command: CommandName,
    *,
    confidence: float = 0.95,
    method: MatchMethod | None = None,
    monitor: int | None = None,
    layout: int | None = None,
    size_inches: int | None = None,
    raw_fragment: str | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=confidence,
        method=method or (MatchMethod.llm if confidence != 1.0 else MatchMethod.entity_rule),
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


def test_choose_better_entity_rule_wins_over_llm() -> None:
    entity = _command(
        CommandName.SET_SIZE,
        method=MatchMethod.entity_rule,
        confidence=1.0,
        size_inches=75,
    )
    llm = _command(
        CommandName.SET_SIZE,
        method=MatchMethod.llm,
        confidence=0.99,
        monitor=2,
        size_inches=75,
    )

    assert choose_better_command(entity, llm) is entity


def test_choose_better_llm_wins_over_fuzzy_for_same_key() -> None:
    llm = _command(
        CommandName.MOVE_RIGHT,
        method=MatchMethod.llm,
        confidence=0.8,
    )
    fuzzy = _command(
        CommandName.MOVE_RIGHT,
        method=MatchMethod.fuzzy,
        confidence=1.0,
    )

    assert choose_better_command(llm, fuzzy) is llm


def test_choose_better_higher_confidence_wins_for_same_method() -> None:
    lower = _command(
        CommandName.MOVE_RIGHT,
        method=MatchMethod.llm,
        confidence=0.8,
    )
    higher = _command(
        CommandName.MOVE_RIGHT,
        method=MatchMethod.llm,
        confidence=0.9,
    )

    assert choose_better_command(lower, higher) is higher


def test_semantic_dedup_keeps_logical_first_key_order() -> None:
    commands = [
        _command(CommandName.MOVE_RIGHT, method=MatchMethod.llm, confidence=0.8),
        _command(CommandName.SELECT_MONITOR, method=MatchMethod.entity_rule, monitor=2),
        _command(CommandName.MOVE_RIGHT, method=MatchMethod.fuzzy, confidence=0.9),
    ]

    deduped = deduplicate_commands_semantically(commands)

    assert [command.command for command in deduped] == [
        CommandName.MOVE_RIGHT,
        CommandName.SELECT_MONITOR,
    ]
    assert deduped[0].method == MatchMethod.llm


def test_semantic_dedup_does_not_duplicate_set_size_75() -> None:
    commands = [
        _command(
            CommandName.SET_SIZE,
            method=MatchMethod.entity_rule,
            confidence=1.0,
            size_inches=75,
        ),
        _command(
            CommandName.SET_SIZE,
            method=MatchMethod.llm,
            confidence=0.9,
            monitor=2,
            size_inches=75,
        ),
    ]

    deduped = deduplicate_commands_semantically(commands)

    assert len(deduped) == 1
    assert deduped[0].size_inches == 75
    assert deduped[0].method == MatchMethod.entity_rule


def test_semantic_dedup_does_not_duplicate_select_monitor_2() -> None:
    commands = [
        _command(
            CommandName.SELECT_MONITOR,
            method=MatchMethod.llm,
            confidence=0.9,
            monitor=2,
        ),
        _command(
            CommandName.SELECT_MONITOR,
            method=MatchMethod.entity_rule,
            confidence=1.0,
            monitor=2,
        ),
    ]

    deduped = deduplicate_commands_semantically(commands)

    assert len(deduped) == 1
    assert deduped[0].monitor == 2
    assert deduped[0].method == MatchMethod.entity_rule


def test_merge_conflicting_set_size_keeps_best_and_marks_confirmation() -> None:
    base = _response(
        [
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.entity_rule,
                confidence=1.0,
                size_inches=75,
            )
        ],
        raw_text="set size",
        normalized_text="set size",
    )
    llm = _response(
        [
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.llm,
                confidence=0.9,
                size_inches=72,
            )
        ],
        raw_text=base.raw_text,
        normalized_text=base.normalized_text,
    )

    merged = merge_command_results(base, llm)

    assert [command.command for command in merged.commands] == [CommandName.SET_SIZE]
    assert merged.commands[0].size_inches == 75
    assert merged.commands[0].method == MatchMethod.entity_rule
    assert merged.needs_confirmation is True
    assert "conflict" in (merged.message or "").lower()


def test_detect_set_size_conflict() -> None:
    conflicts = detect_command_conflicts(
        [
            _command(CommandName.SET_SIZE, size_inches=75),
            _command(CommandName.SET_SIZE, size_inches=72),
        ]
    )

    assert conflicts == [
        {
            "type": "set_size_conflict",
            "values": [72, 75],
            "message": "Conflicting SET_SIZE commands detected",
        }
    ]


def test_merge_select_monitor_conflict_marks_confirmation() -> None:
    base = _response(
        [_command(CommandName.SELECT_MONITOR, method=MatchMethod.entity_rule, monitor=1)]
    )
    llm = _response(
        [_command(CommandName.SELECT_MONITOR, method=MatchMethod.llm, monitor=2)]
    )

    merged = merge_command_results(base, llm)

    assert merged.needs_confirmation is True
    assert "select_monitor" in (merged.message or "").lower()


def test_merge_set_layout_conflict_marks_confirmation() -> None:
    base = _response(
        [_command(CommandName.SET_LAYOUT, method=MatchMethod.entity_rule, layout=1)]
    )
    llm = _response(
        [_command(CommandName.SET_LAYOUT, method=MatchMethod.llm, layout=2)]
    )

    merged = merge_command_results(base, llm)

    assert merged.needs_confirmation is True
    assert "set_layout" in (merged.message or "").lower()


def test_same_set_size_deduplicates_without_conflict() -> None:
    base = _response(
        [
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.entity_rule,
                confidence=1.0,
                size_inches=75,
            )
        ]
    )
    llm = _response(
        [
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.llm,
                confidence=0.9,
                monitor=2,
                size_inches=75,
            )
        ]
    )

    merged = merge_command_results(base, llm)

    assert [command.command for command in merged.commands] == [CommandName.SET_SIZE]
    assert merged.commands[0].size_inches == 75
    assert merged.needs_confirmation is False
    assert "conflict" not in (merged.message or "").lower()


def test_merge_opposite_horizontal_movement_marks_confirmation() -> None:
    base = _response([_command(CommandName.MOVE_LEFT, method=MatchMethod.exact_rule)])
    llm = _response([_command(CommandName.MOVE_RIGHT, method=MatchMethod.llm)])

    merged = merge_command_results(base, llm)

    assert merged.needs_confirmation is True
    assert "movement" in (merged.message or "").lower()


def test_merge_opposite_vertical_movement_marks_confirmation() -> None:
    base = _response([_command(CommandName.MOVE_UP, method=MatchMethod.exact_rule)])
    llm = _response([_command(CommandName.MOVE_DOWN, method=MatchMethod.llm)])

    merged = merge_command_results(base, llm)

    assert merged.needs_confirmation is True
    assert "movement" in (merged.message or "").lower()
