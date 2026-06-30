from __future__ import annotations

import app.normalizer as normalizer_module
from app.fuzzy_matcher import clear_fuzzy_cache
from app.normalizer import normalize_command_text
from app.schemas import CommandName


def _assert_single_command(
    text: str,
    command_name: CommandName,
    *,
    monitor: int | None = None,
    layout: int | None = None,
    size_inches: int | None = None,
) -> None:
    response = normalize_command_text(text)
    assert [command.command for command in response.commands] == [command_name]
    command = response.commands[0]
    assert command.monitor == monitor
    assert command.layout == layout
    assert command.size_inches == size_inches
    assert response.needs_confirmation is False


def test_normalize_monitor_one() -> None:
    _assert_single_command("monitor one", CommandName.SELECT_MONITOR, monitor=1)


def test_normalize_monitor_two() -> None:
    _assert_single_command("monitor two", CommandName.SELECT_MONITOR, monitor=2)


def test_normalize_left() -> None:
    _assert_single_command("left", CommandName.MOVE_LEFT)


def test_normalize_right() -> None:
    _assert_single_command("right", CommandName.MOVE_RIGHT)


def test_normalize_up() -> None:
    _assert_single_command("up", CommandName.MOVE_UP)


def test_normalize_down() -> None:
    _assert_single_command("down", CommandName.MOVE_DOWN)


def test_normalize_zoom_in() -> None:
    _assert_single_command("zoom in", CommandName.ZOOM_IN)


def test_normalize_zoom_out() -> None:
    _assert_single_command("zoom out", CommandName.ZOOM_OUT)


def test_normalize_increase() -> None:
    _assert_single_command("increase", CommandName.INCREASE_SIZE)


def test_normalize_decrease() -> None:
    _assert_single_command("decrease", CommandName.DECREASE_SIZE)


def test_normalize_set_size_55() -> None:
    _assert_single_command("55 inch", CommandName.SET_SIZE, size_inches=55)


def test_normalize_set_size_120_spanish() -> None:
    _assert_single_command("120 pulgadas", CommandName.SET_SIZE, size_inches=120)


def test_normalize_follow_me() -> None:
    _assert_single_command("follow me", CommandName.FOLLOW_ME)


def test_normalize_stop_follow_me() -> None:
    _assert_single_command("stop follow me", CommandName.STOP_FOLLOW_ME)


def test_normalize_recenter_objects() -> None:
    _assert_single_command("recenter objects", CommandName.RECENTER_OBJECTS)


def test_normalize_center_objects() -> None:
    _assert_single_command("center objects", CommandName.RECENTER_OBJECTS)


def test_normalize_reset_position() -> None:
    _assert_single_command("reset position", CommandName.RESET_POSITION)


def test_normalize_layout_one() -> None:
    _assert_single_command("layout one", CommandName.SET_LAYOUT, layout=1)


def test_normalize_layout_two() -> None:
    _assert_single_command("layout two", CommandName.SET_LAYOUT, layout=2)


def test_normalize_show_aitrol() -> None:
    _assert_single_command("show aitrol", CommandName.SHOW_AITROL)


def test_normalize_close_aitrol() -> None:
    _assert_single_command("close aitrol", CommandName.CLOSE_AITROL)


def test_normalize_show_voice_commands() -> None:
    _assert_single_command("show voice commands", CommandName.SHOW_VOICE_COMMANDS)


def test_normalize_close_voice_commands() -> None:
    _assert_single_command("close voice commands", CommandName.CLOSE_VOICE_COMMANDS)


def test_normalize_settings() -> None:
    _assert_single_command("settings", CommandName.OPEN_SETTINGS)


def test_normalize_capture() -> None:
    _assert_single_command("capture", CommandName.CAPTURE)


def test_normalize_stream() -> None:
    _assert_single_command("stream", CommandName.START_STREAM)


def test_normalize_record() -> None:
    _assert_single_command("record", CommandName.START_RECORDING)


def test_normalize_stop_stream() -> None:
    _assert_single_command("stop stream", CommandName.STOP_STREAM)


def test_normalize_stop() -> None:
    _assert_single_command("stop", CommandName.STOP_ACTIVE)


def test_normalize_monitor_and_zoom_in() -> None:
    response = normalize_command_text("monitor two and zoom in")
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.ZOOM_IN,
    ]
    assert response.commands[0].monitor == 2
    assert response.needs_confirmation is False


def test_normalize_monitor_uno_y_acercalo() -> None:
    response = normalize_command_text("monitor uno y acercalo")
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.ZOOM_IN,
    ]
    assert response.commands[0].monitor == 1
    assert response.needs_confirmation is False


def test_normalize_multi_command_spanish_sequence() -> None:
    response = normalize_command_text(
        "monitor dos, muevelo a la izquierda y ponlo en 65 pulgadas"
    )
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.MOVE_LEFT,
        CommandName.SET_SIZE,
    ]
    assert response.commands[0].monitor == 2
    assert response.commands[2].size_inches == 65
    assert response.needs_confirmation is False


def test_normalize_monitor_and_absolute_size_with_joined_unit() -> None:
    response = normalize_command_text("hola cambia el tamaño de la pantalla 2 a 55inch")
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert response.commands[0].monitor == 2
    assert response.commands[1].size_inches == 55


def test_normalize_audio_transcription_size_typo_sequence() -> None:
    response = normalize_command_text(
        "pantalla 2 mueve la la derecha y luego las es en el tamaño de 55 puladas",
        language_hint="es",
    )
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.MOVE_RIGHT,
        CommandName.SET_SIZE,
    ]
    assert response.commands[0].monitor == 2
    assert response.commands[2].size_inches == 55
    assert response.needs_confirmation is False


def test_normalize_unknown_returns_confirmation(monkeypatch) -> None:
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_bool_setting",
        lambda key, default: False
        if key in {"ENABLE_SEMANTIC_MATCHER", "ENABLE_OLLAMA_FALLBACK"}
        else default,
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

    response = normalize_command_text("abracadabra orbital")
    assert [command.command for command in response.commands] == [CommandName.UNKNOWN]
    assert response.needs_confirmation is True


def test_normalize_uses_language_hint() -> None:
    response = normalize_command_text("left", language_hint="en")
    assert response.language == "en"


def test_normalize_uses_ollama_fallback_when_enabled(monkeypatch) -> None:
    monkeypatch.setattr(normalizer_module, "ENABLE_SEMANTIC_MATCHER", False)
    monkeypatch.setattr(normalizer_module, "ENABLE_OLLAMA_FALLBACK", True)
    monkeypatch.setattr(
        normalizer_module,
        "ollama_fallback_normalize",
        lambda text, normalized_text, language_hint=None: normalizer_module.NormalizeResponse(
            ok=True,
            raw_text=text,
            normalized_text=normalized_text,
            language=language_hint,
            commands=[
                normalizer_module.NormalizedCommand(
                    command=CommandName.START_STREAM,
                    confidence=0.70,
                    method=normalizer_module.MatchMethod.llm,
                    raw_fragment=normalized_text,
                )
            ],
            needs_confirmation=True,
            message=None,
        ),
    )

    response = normalize_command_text("begin live video", language_hint="en")
    assert [command.command for command in response.commands] == [CommandName.START_STREAM]
    assert response.needs_confirmation is True


def test_normalize_ignores_ollama_failure(monkeypatch) -> None:
    monkeypatch.setattr(normalizer_module, "ENABLE_SEMANTIC_MATCHER", False)
    monkeypatch.setattr(normalizer_module, "ENABLE_OLLAMA_FALLBACK", True)
    monkeypatch.setattr(
        normalizer_module,
        "ollama_fallback_normalize",
        lambda text, normalized_text, language_hint=None: None,
    )

    response = normalize_command_text("abracadabra orbital")
    assert [command.command for command in response.commands] == [CommandName.UNKNOWN]


def test_normalize_rejects_text_above_max_length(monkeypatch) -> None:
    monkeypatch.setattr(normalizer_module, "MAX_TEXT_LENGTH", 10)
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_int_setting",
        lambda key, default: 10 if key == "MAX_TEXT_LENGTH" else default,
    )
    response = normalize_command_text("this input is definitely too long")
    assert response.ok is False
    assert response.needs_confirmation is True
    assert [command.command for command in response.commands] == [CommandName.UNKNOWN]
    assert "maximum length" in (response.message or "")


def test_normalizer_uses_runtime_db_threshold(monkeypatch) -> None:
    clear_fuzzy_cache()
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_float_setting",
        lambda key, default: 95.0 if key == "FUZZY_THRESHOLD" else default,
    )
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_int_setting",
        lambda key, default: default,
    )
    monkeypatch.setattr(
        normalizer_module.runtime_settings_service,
        "get_bool_setting",
        lambda key, default: False if key in {"ENABLE_SEMANTIC_MATCHER", "ENABLE_OLLAMA_FALLBACK"} else default,
    )

    response = normalize_command_text("stram")
    assert [command.command for command in response.commands] == [CommandName.UNKNOWN]


def test_normalizer_uses_config_when_runtime_settings_fail(monkeypatch) -> None:
    clear_fuzzy_cache()
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
        "get_bool_setting",
        lambda key, default: False if key in {"ENABLE_SEMANTIC_MATCHER", "ENABLE_OLLAMA_FALLBACK"} else default,
    )

    response = normalize_command_text("stram")
    assert [command.command for command in response.commands] == [CommandName.START_STREAM]
