from __future__ import annotations

import app.normalizer as normalizer_module
from app.normalizer import normalize_command_text
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services import size_validation_service
from app.services.command_merge_service import merge_command_results


def _patch_hybrid_runtime(monkeypatch) -> None:
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_bool_setting",
        lambda key, default: {
            "ENABLE_SEMANTIC_MATCHER": False,
            "ENABLE_OLLAMA_FALLBACK": True,
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
        lambda key, default: "hybrid" if key == "LLM_COMMAND_MODE" else default,
    )
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_runtime_bool_setting",
        lambda key, default: True
        if key == "ALLOW_DYNAMIC_SIZE_INCHES"
        else default,
    )
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_runtime_int_setting",
        lambda key, default: {
            "MIN_SIZE_INCHES": 40,
            "MAX_SIZE_INCHES": 150,
        }.get(key, default),
    )


def _command(
    command: CommandName,
    *,
    method: MatchMethod = MatchMethod.entity_rule,
    confidence: float = 1.0,
    monitor: int | None = None,
    size_inches: int | None = None,
    raw_fragment: str | None = None,
) -> NormalizedCommand:
    return NormalizedCommand(
        command=command,
        confidence=confidence,
        method=method,
        monitor=monitor,
        size_inches=size_inches,
        raw_fragment=raw_fragment or command.value.lower(),
    )


def _response(
    commands: list[NormalizedCommand],
    *,
    raw_text: str = "Necesito que el monitor 2 esté en 75 pulgadas",
    normalized_text: str = "necesito que el monitor 2 este en 75 pulgadas",
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


def _set_size_commands(response: NormalizeResponse) -> list[NormalizedCommand]:
    return [
        command
        for command in response.commands
        if command.command == CommandName.SET_SIZE
    ]


def test_complete_monitor_size_phrase_should_not_call_llm(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _response(
            [
                _command(
                    CommandName.SET_SIZE,
                    method=MatchMethod.llm,
                    confidence=0.9,
                    monitor=2,
                    size_inches=75,
                    raw_fragment="75 pulgadas",
                )
            ]
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text(
        "Necesito que el monitor 2 esté en 75 pulgadas",
        language_hint="es",
    )

    assert calls == []
    assert "LLM used" not in (response.message or "")
    assert response.needs_confirmation is False
    assert response.commands[0].command == CommandName.SELECT_MONITOR
    assert response.commands[0].monitor == 2
    set_size_commands = _set_size_commands(response)
    assert len(set_size_commands) == 1
    assert set_size_commands[0].size_inches == 75
    assert set_size_commands[0].method == MatchMethod.entity_rule


def test_if_llm_returns_duplicate_set_size_merge_keeps_one() -> None:
    base_response = _response(
        [
            _command(CommandName.SELECT_MONITOR, monitor=2, raw_fragment="monitor 2"),
            _command(CommandName.SET_SIZE, size_inches=75, raw_fragment="75 pulgadas"),
        ]
    )
    llm_response = _response(
        [
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.llm,
                confidence=0.9,
                monitor=2,
                size_inches=75,
                raw_fragment="75 pulgadas",
            )
        ]
    )

    merged = merge_command_results(base_response, llm_response)

    assert [command.command for command in merged.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert merged.commands[0].monitor == 2
    set_size_commands = _set_size_commands(merged)
    assert len(set_size_commands) == 1
    assert set_size_commands[0].size_inches == 75
    assert set_size_commands[0].method == MatchMethod.entity_rule


def test_conflicting_size_should_mark_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True if key == "ALLOW_DYNAMIC_SIZE_INCHES" else default,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {
            "MIN_SIZE_INCHES": 40,
            "MAX_SIZE_INCHES": 150,
        }.get(key, default),
    )
    base_response = _response(
        [
            _command(CommandName.SET_SIZE, size_inches=75, raw_fragment="75 pulgadas"),
        ]
    )
    llm_response = _response(
        [
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.llm,
                confidence=0.9,
                size_inches=72,
                raw_fragment="72 pulgadas",
            )
        ]
    )

    merged = merge_command_results(base_response, llm_response)

    set_size_commands = _set_size_commands(merged)
    assert len(set_size_commands) == 1
    assert merged.needs_confirmation is True
    assert merged.message is not None
    assert "conflict" in merged.message.lower()
