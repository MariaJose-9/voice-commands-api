from __future__ import annotations

from app.preprocessor import normalize_text
from app.schemas import CommandName, MatchMethod, NormalizedCommand
from app.services.completeness_checker import check_command_completeness


def _command(
    command: CommandName,
    raw_fragment: str | None = None,
    *,
    monitor: int | None = None,
    size_inches: int | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=1.0,
        method=MatchMethod.exact_rule,
        monitor=monitor,
        size_inches=size_inches,
        raw_fragment=raw_fragment,
    )


def test_monitor_only_is_complete() -> None:
    result = check_command_completeness(
        normalize_text("monitor 1"),
        [_command(CommandName.SELECT_MONITOR, "monitor 1", monitor=1)],
    )

    assert result.is_complete is True
    assert result.should_call_llm is False


def test_missing_set_size_for_explicit_absolute_size_intent() -> None:
    result = check_command_completeness(
        normalize_text("Redimensiona a 72 pulgadas el monitor 1"),
        [_command(CommandName.SELECT_MONITOR, "monitor 1", monitor=1)],
    )

    assert result.is_complete is False
    assert result.should_call_llm is True
    assert result.reason == "explicit_size_intent_missing_set_size"
    assert "set_size" in result.unresolved_intents


def test_complete_monitor_size_phrase_with_select_monitor_and_set_size() -> None:
    result = check_command_completeness(
        normalize_text("Necesito que el monitor 2 esté en 75 pulgadas"),
        [
            _command(CommandName.SELECT_MONITOR, "monitor 2", monitor=2),
            _command(CommandName.SET_SIZE, "75 pulgadas", size_inches=75),
        ],
    )

    assert result.is_complete is True
    assert result.should_call_llm is False


def test_missing_set_size_when_monitor_detected_but_size_not_detected() -> None:
    result = check_command_completeness(
        normalize_text("Necesito que el monitor 2 esté en 75 pulgadas"),
        [_command(CommandName.SELECT_MONITOR, "monitor 2", monitor=2)],
    )

    assert result.is_complete is False
    assert result.should_call_llm is True
    assert result.reason == "explicit_size_intent_missing_set_size"


def test_missing_increase_size_intent() -> None:
    result = check_command_completeness(
        normalize_text("haz más grande el monitor 1"),
        [_command(CommandName.SELECT_MONITOR, "monitor 1", monitor=1)],
    )

    assert result.should_call_llm is True
    assert result.reason == "increase_size_intent_missing_command"
    assert "increase_size" in result.unresolved_intents


def test_missing_movement_intent() -> None:
    result = check_command_completeness(
        normalize_text("monitor dos a la derecha"),
        [_command(CommandName.SELECT_MONITOR, "monitor dos", monitor=2)],
    )

    assert result.should_call_llm is True
    assert result.reason == "movement_intent_missing_command"
    assert "move_right" in result.unresolved_intents


def test_complete_monitor_movement_phrase() -> None:
    result = check_command_completeness(
        normalize_text("monitor dos a la derecha"),
        [
            _command(CommandName.SELECT_MONITOR, "monitor dos", monitor=2),
            _command(CommandName.MOVE_RIGHT, "derecha"),
        ],
    )

    assert result.is_complete is True
    assert result.should_call_llm is False


def test_left_only_is_complete() -> None:
    result = check_command_completeness(
        normalize_text("left"),
        [_command(CommandName.MOVE_LEFT, "left")],
    )

    assert result.is_complete is True
    assert result.should_call_llm is False


def test_no_commands_should_call_llm() -> None:
    result = check_command_completeness(normalize_text("abracadabra"), [])

    assert result.is_complete is False
    assert result.should_call_llm is True
    assert result.reason == "no_commands"


def test_unknown_command_should_call_llm() -> None:
    result = check_command_completeness(
        normalize_text("abracadabra"),
        [_command(CommandName.UNKNOWN, "abracadabra")],
    )

    assert result.is_complete is False
    assert result.should_call_llm is True
    assert result.reason == "unknown_command"
