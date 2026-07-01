from __future__ import annotations

import app.normalizer as normalizer_module
from app.normalizer import normalize_command_text
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services import size_validation_service


def _patch_runtime(
    monkeypatch,
    *,
    mode: str,
    enable_semantic: bool = False,
    enable_ollama: bool = True,
) -> None:
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_bool_setting",
        lambda key, default: {
            "ENABLE_SEMANTIC_MATCHER": enable_semantic,
            "ENABLE_OLLAMA_FALLBACK": enable_ollama,
        }.get(key, default),
    )
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_float_setting",
        lambda key, default: default,
    )
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_int_setting",
        lambda key, default: default,
    )
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_runtime_str_setting",
        lambda key, default: mode if key == "LLM_COMMAND_MODE" else default,
    )


def _llm_response(
    raw_text: str,
    normalized_text: str,
    commands: list[NormalizedCommand],
) -> NormalizeResponse:
    return NormalizeResponse(
        ok=True,
        raw_text=raw_text,
        normalized_text=normalized_text,
        language="es",
        commands=commands,
        needs_confirmation=False,
        message=None,
    )


def _command(
    command: CommandName,
    *,
    monitor: int | None = None,
    size_inches: int | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=0.95,
        method=MatchMethod.llm,
        monitor=monitor,
        size_inches=size_inches,
        raw_fragment=command.value.lower(),
    )


def test_llm_mode_off_does_not_call_llm_for_incomplete_size(monkeypatch) -> None:
    _patch_runtime(monkeypatch, mode="off")
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Redimensiona a 72 pulgadas el monitor 1")

    assert called["value"] is False
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR
    ]


def test_hybrid_calls_llm_when_base_missing_set_size(monkeypatch) -> None:
    _patch_runtime(monkeypatch, mode="hybrid")
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {"MIN_SIZE_INCHES": 40, "MAX_SIZE_INCHES": 150}[key],
    )
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            kwargs["raw_text"],
            kwargs["normalized_text"],
            [
                _command(CommandName.SELECT_MONITOR, monitor=1),
                _command(CommandName.SET_SIZE, size_inches=72),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Redimensiona a 72 pulgadas el monitor 1")

    assert calls
    assert calls[0]["previous_commands"][0].command == CommandName.SELECT_MONITOR
    assert calls[0]["completeness_reason"] == "explicit_size_intent_missing_set_size"
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert response.commands[0].monitor == 1
    assert response.commands[1].size_inches == 72


def test_monitor_only_does_not_call_llm_in_hybrid(monkeypatch) -> None:
    _patch_runtime(monkeypatch, mode="hybrid")
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("monitor 1")

    assert called["value"] is False
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR
    ]


def test_left_does_not_call_llm_in_hybrid(monkeypatch) -> None:
    _patch_runtime(monkeypatch, mode="hybrid")
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("left")

    assert called["value"] is False
    assert [command.command for command in response.commands] == [CommandName.MOVE_LEFT]


def test_hybrid_calls_llm_for_missing_increase_size(monkeypatch) -> None:
    _patch_runtime(monkeypatch, mode="hybrid")
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            kwargs["raw_text"],
            kwargs["normalized_text"],
            [
                _command(CommandName.SELECT_MONITOR, monitor=1),
                _command(CommandName.INCREASE_SIZE),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("haz más grande el monitor 1")

    assert calls
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.INCREASE_SIZE,
    ]


def test_fallback_mode_does_not_call_llm_for_complete_low_coverage_base(
    monkeypatch,
) -> None:
    _patch_runtime(monkeypatch, mode="fallback")
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Redimensiona a 72 pulgadas el monitor 1")

    assert called["value"] is False
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR
    ]


def test_primary_mode_calls_llm_first(monkeypatch) -> None:
    _patch_runtime(monkeypatch, mode="primary", enable_ollama=False)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            kwargs["raw_text"],
            kwargs["normalized_text"],
            [_command(CommandName.MOVE_RIGHT)],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("right")

    assert calls
    assert calls[0]["previous_commands"] == []
    assert calls[0]["completeness_reason"] == "primary"
    assert [command.command for command in response.commands] == [CommandName.MOVE_RIGHT]
