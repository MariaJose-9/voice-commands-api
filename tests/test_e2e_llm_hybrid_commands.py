from __future__ import annotations

import app.normalizer as normalizer_module
from app.normalizer import normalize_command_text
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand


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


def _llm_response(
    *,
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


def _assert_contains(
    response: NormalizeResponse,
    expected: list[dict],
) -> None:
    actual = response.commands
    assert CommandName.UNKNOWN not in [command.command for command in actual]

    for expected_command in expected:
        matched = False
        for command in actual:
            if command.command != expected_command["command"]:
                continue
            if (
                "monitor" in expected_command
                and command.monitor != expected_command["monitor"]
            ):
                continue
            if (
                "size_inches" in expected_command
                and command.size_inches != expected_command["size_inches"]
            ):
                continue
            matched = True
            break
        assert matched, {
            "missing": expected_command,
            "actual": [command.model_dump(mode="json") for command in actual],
        }


def test_hybrid_completes_redimensiona_size_before_monitor(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            commands=[
                _command(CommandName.SELECT_MONITOR, monitor=1),
                _command(CommandName.SET_SIZE, size_inches=72),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Redimensiona a 72 pulgadas el monitor 1")

    assert calls
    _assert_contains(
        response,
        [
            {"command": CommandName.SELECT_MONITOR, "monitor": 1},
            {"command": CommandName.SET_SIZE, "size_inches": 72},
        ],
    )


def test_hybrid_completes_redimensiona_size_after_monitor(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            commands=[
                _command(CommandName.SELECT_MONITOR, monitor=1),
                _command(CommandName.SET_SIZE, size_inches=72),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Redimensiona el monitor 1 a 72 pulgadas")

    assert calls
    _assert_contains(
        response,
        [
            {"command": CommandName.SELECT_MONITOR, "monitor": 1},
            {"command": CommandName.SET_SIZE, "size_inches": 72},
        ],
    )


def test_hybrid_completes_ajusta_pantalla_dos_dynamic_size(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            commands=[
                _command(CommandName.SELECT_MONITOR, monitor=2),
                _command(CommandName.SET_SIZE, size_inches=80),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Ajusta la pantalla dos a 80 pulgadas")

    assert calls
    _assert_contains(
        response,
        [
            {"command": CommandName.SELECT_MONITOR, "monitor": 2},
            {"command": CommandName.SET_SIZE, "size_inches": 80},
        ],
    )


def test_hybrid_completes_haz_mas_chico_monitor_dos(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            commands=[
                _command(CommandName.SELECT_MONITOR, monitor=2),
                _command(CommandName.DECREASE_SIZE),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Haz más chico el monitor dos")

    assert calls
    _assert_contains(
        response,
        [
            {"command": CommandName.SELECT_MONITOR, "monitor": 2},
            {"command": CommandName.DECREASE_SIZE},
        ],
    )


def test_hybrid_completes_haz_mas_grande_monitor_uno(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            commands=[
                _command(CommandName.SELECT_MONITOR, monitor=1),
                _command(CommandName.INCREASE_SIZE),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("Haz más grande el monitor uno")

    assert calls
    _assert_contains(
        response,
        [
            {"command": CommandName.SELECT_MONITOR, "monitor": 1},
            {"command": CommandName.INCREASE_SIZE},
        ],
    )


def test_hybrid_does_not_call_llm_for_monitor_only(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("monitor 1")

    assert called["value"] is False
    _assert_contains(response, [{"command": CommandName.SELECT_MONITOR, "monitor": 1}])


def test_hybrid_does_not_call_llm_for_left_only(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    called = {"value": False}

    def fake_llm(**kwargs):
        called["value"] = True
        return None

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("left")

    assert called["value"] is False
    _assert_contains(response, [{"command": CommandName.MOVE_LEFT}])


def test_hybrid_completes_movement_and_dynamic_resize(monkeypatch) -> None:
    _patch_hybrid_runtime(monkeypatch)
    calls: list[dict] = []

    def fake_llm(**kwargs):
        calls.append(kwargs)
        return _llm_response(
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            commands=[
                _command(CommandName.SELECT_MONITOR, monitor=1),
                _command(CommandName.MOVE_RIGHT),
                _command(CommandName.SET_SIZE, size_inches=72),
            ],
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text(
        "Mueve el monitor uno a la derecha y redimensiónalo a 72 pulgadas"
    )

    assert calls
    _assert_contains(
        response,
        [
            {"command": CommandName.SELECT_MONITOR, "monitor": 1},
            {"command": CommandName.MOVE_RIGHT},
            {"command": CommandName.SET_SIZE, "size_inches": 72},
        ],
    )
