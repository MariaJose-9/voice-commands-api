from __future__ import annotations

import app.normalizer as normalizer_module
from app.normalizer import normalize_command_text
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand


_MOVEMENT_COMMANDS = {
    CommandName.MOVE_LEFT,
    CommandName.MOVE_RIGHT,
    CommandName.MOVE_UP,
    CommandName.MOVE_DOWN,
}


def _command_names(response: NormalizeResponse) -> list[CommandName]:
    return [command.command for command in response.commands]


def _assert_has(
    response: NormalizeResponse,
    command_name: CommandName,
    *,
    monitor: int | None = None,
) -> NormalizedCommand:
    for command in response.commands:
        if command.command != command_name:
            continue
        if monitor is not None and command.monitor != monitor:
            continue
        return command

    raise AssertionError(
        {
            "missing": command_name.value,
            "monitor": monitor,
            "actual": [command.model_dump(mode="json") for command in response.commands],
        }
    )


def _assert_no_movement(response: NormalizeResponse) -> None:
    assert not (_MOVEMENT_COMMANDS & set(_command_names(response)))


def test_aleja_monitor_2_with_distance_is_zoom_out() -> None:
    response = normalize_command_text("aleja el monitor 2, 1 metro")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=2)
    zoom = _assert_has(response, CommandName.ZOOM_OUT)
    assert zoom.value == "1 metro"
    _assert_no_movement(response)


def test_split_asr_aleja_monitor_2_with_distance_is_zoom_out() -> None:
    response = normalize_command_text("a leja el monitor 2 1 metro")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=2)
    _assert_has(response, CommandName.ZOOM_OUT)
    _assert_no_movement(response)


def test_aleja_monitor_dos_is_zoom_out() -> None:
    response = normalize_command_text("aleja el monitor dos")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=2)
    _assert_has(response, CommandName.ZOOM_OUT)
    _assert_no_movement(response)


def test_acerca_monitor_1_is_zoom_in() -> None:
    response = normalize_command_text("acerca el monitor 1")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=1)
    _assert_has(response, CommandName.ZOOM_IN)
    _assert_no_movement(response)


def test_split_asr_acerca_monitor_uno_is_zoom_in() -> None:
    response = normalize_command_text("a cerca el monitor uno")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=1)
    _assert_has(response, CommandName.ZOOM_IN)
    _assert_no_movement(response)


def test_aleja_pantalla_dos_is_zoom_out() -> None:
    response = normalize_command_text("aleja la pantalla dos")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=2)
    _assert_has(response, CommandName.ZOOM_OUT)
    _assert_no_movement(response)


def test_acerca_pantalla_una_is_zoom_in() -> None:
    response = normalize_command_text("acerca la pantalla una")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=1)
    _assert_has(response, CommandName.ZOOM_IN)
    _assert_no_movement(response)


def test_mueve_monitor_2_derecha_remains_move_right() -> None:
    response = normalize_command_text("mueve el monitor 2 a la derecha")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=2)
    _assert_has(response, CommandName.MOVE_RIGHT)
    assert CommandName.ZOOM_OUT not in _command_names(response)


def test_aleja_monitor_2_derecha_has_zoom_and_movement() -> None:
    response = normalize_command_text("aleja el monitor 2 a la derecha")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=2)
    _assert_has(response, CommandName.ZOOM_OUT)
    _assert_has(response, CommandName.MOVE_RIGHT)


def test_llm_movement_for_zoom_out_is_guardrailed(monkeypatch) -> None:
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
        lambda key, default: "primary" if key == "LLM_COMMAND_MODE" else default,
    )

    def fake_llm(**kwargs):
        return NormalizeResponse(
            ok=True,
            raw_text=kwargs["raw_text"],
            normalized_text=kwargs["normalized_text"],
            language=kwargs["language_hint"],
            commands=[
                NormalizedCommand(
                    command=CommandName.SELECT_MONITOR,
                    confidence=0.95,
                    method=MatchMethod.llm,
                    monitor=2,
                    raw_fragment="monitor 2",
                ),
                NormalizedCommand(
                    command=CommandName.MOVE_RIGHT,
                    confidence=0.95,
                    method=MatchMethod.llm,
                    raw_fragment="move right",
                ),
            ],
            needs_confirmation=False,
            message=None,
        )

    monkeypatch.setattr(normalizer_module, "interpret_commands_with_llm", fake_llm)

    response = normalize_command_text("aleja el monitor 2, 1 metro")

    _assert_has(response, CommandName.SELECT_MONITOR, monitor=2)
    zoom = _assert_has(response, CommandName.ZOOM_OUT)
    assert zoom.value == "1 metro"
    _assert_no_movement(response)
