from __future__ import annotations

import app.normalizer as normalizer_module
from app.normalizer import normalize_command_text
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services import size_validation_service
from app.services.command_merge_service import merge_command_results


def _patch_hybrid_runtime(monkeypatch) -> None:
    """Force hybrid LLM settings without requiring DB or Ollama."""

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
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True
        if key == "ALLOW_DYNAMIC_SIZE_INCHES"
        else default,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {
            "MIN_SIZE_INCHES": 40,
            "MAX_SIZE_INCHES": 150,
        }.get(key, default),
    )


def _command(
    command: CommandName,
    *,
    method: MatchMethod = MatchMethod.llm,
    confidence: float = 0.95,
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
        ok=all(command.command != CommandName.UNKNOWN for command in commands),
        raw_text=raw_text,
        normalized_text=normalized_text,
        language="es",
        commands=commands,
        needs_confirmation=False,
        message=None,
    )


def _commands_named(response: NormalizeResponse, command_name: CommandName) -> list[NormalizedCommand]:
    return [command for command in response.commands if command.command == command_name]


def _assert_has_command(
    response: NormalizeResponse,
    command_name: CommandName,
    *,
    monitor: int | None = None,
    size_inches: int | None = None,
) -> NormalizedCommand:
    for command in response.commands:
        if command.command != command_name:
            continue
        if monitor is not None and command.monitor != monitor:
            continue
        if size_inches is not None and command.size_inches != size_inches:
            continue
        return command

    raise AssertionError(
        {
            "missing": {
                "command": command_name.value,
                "monitor": monitor,
                "size_inches": size_inches,
            },
            "actual": [command.model_dump(mode="json") for command in response.commands],
        }
    )


def test_base_complete_monitor_size_phrase_should_not_call_llm(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _response(
            [
                _command(
                    CommandName.SET_SIZE,
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
    _assert_has_command(response, CommandName.SELECT_MONITOR, monitor=2)
    set_size = _assert_has_command(response, CommandName.SET_SIZE, size_inches=75)
    assert set_size.method == MatchMethod.entity_rule
    assert len(_commands_named(response, CommandName.SET_SIZE)) == 1
    assert response.needs_confirmation is False


def test_base_incomplete_calls_llm_and_completes_set_size(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _response(
            [
                _command(CommandName.SELECT_MONITOR, monitor=1),
                _command(CommandName.SET_SIZE, size_inches=72),
            ],
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text(
        "Redimensiona a 72 pulgadas el monitor 1",
        language_hint="es",
    )

    assert calls
    _assert_has_command(response, CommandName.SELECT_MONITOR, monitor=1)
    _assert_has_command(response, CommandName.SET_SIZE, size_inches=72)
    assert response.needs_confirmation is False


def test_llm_duplicate_base_set_size_is_removed_and_entity_rule_wins() -> None:
    base_response = _response(
        [
            _command(
                CommandName.SELECT_MONITOR,
                method=MatchMethod.entity_rule,
                confidence=1.0,
                monitor=2,
                raw_fragment="monitor 2",
            ),
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.entity_rule,
                confidence=1.0,
                size_inches=75,
                raw_fragment="75 pulgadas",
            ),
        ]
    )
    llm_response = _response(
        [
            _command(
                CommandName.SET_SIZE,
                monitor=2,
                size_inches=75,
                raw_fragment="75 pulgadas",
            )
        ]
    )

    merged = merge_command_results(base_response, llm_response)

    _assert_has_command(merged, CommandName.SELECT_MONITOR, monitor=2)
    set_size = _assert_has_command(merged, CommandName.SET_SIZE, size_inches=75)
    assert len(_commands_named(merged, CommandName.SET_SIZE)) == 1
    assert set_size.method == MatchMethod.entity_rule


def test_size_conflict_prefers_base_entity_rule_and_requires_confirmation(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    base_response = _response(
        [
            _command(
                CommandName.SELECT_MONITOR,
                method=MatchMethod.entity_rule,
                confidence=1.0,
                monitor=2,
                raw_fragment="monitor 2",
            ),
            _command(
                CommandName.SET_SIZE,
                method=MatchMethod.entity_rule,
                confidence=1.0,
                size_inches=75,
                raw_fragment="75 pulgadas",
            ),
        ]
    )
    llm_response = _response(
        [
            _command(
                CommandName.SET_SIZE,
                size_inches=72,
                raw_fragment="72 pulgadas",
            )
        ]
    )

    merged = merge_command_results(
        base_response,
        llm_response,
        normalized_text=base_response.normalized_text,
        raw_text=base_response.raw_text,
    )

    set_size = _assert_has_command(merged, CommandName.SET_SIZE, size_inches=75)
    assert len(_commands_named(merged, CommandName.SET_SIZE)) == 1
    assert set_size.method == MatchMethod.entity_rule
    assert merged.needs_confirmation is True
    assert merged.message is not None
    assert "conflict" in merged.message.lower()


def test_monitor_conflict_requires_confirmation() -> None:
    base_response = _response(
        [
            _command(
                CommandName.SELECT_MONITOR,
                method=MatchMethod.entity_rule,
                confidence=1.0,
                monitor=2,
                raw_fragment="monitor 2",
            )
        ]
    )
    llm_response = _response(
        [_command(CommandName.SELECT_MONITOR, monitor=1, raw_fragment="monitor 1")]
    )

    merged = merge_command_results(base_response, llm_response)

    assert merged.needs_confirmation is True
    assert merged.message is not None
    assert "conflict" in merged.message.lower()
