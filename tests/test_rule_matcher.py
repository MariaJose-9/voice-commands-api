from app.entity_extractor import extract_entities
from app.preprocessor import normalize_text
from app.rule_matcher import match_by_rules
from app.schemas import CommandName, MatchMethod


def _match(text: str):
    normalized = normalize_text(text)
    entities = extract_entities(normalized)
    return match_by_rules(normalized, entities)


def test_match_stop_follow_me_overrides_follow_me() -> None:
    commands = _match("stop follow me")

    assert [command.command for command in commands] == [CommandName.STOP_FOLLOW_ME]
    assert commands[0].method == MatchMethod.exact_rule
    assert commands[0].raw_fragment == "stop follow me"


def test_match_stop_stream_overrides_stop_active_and_start_stream() -> None:
    commands = _match("stop stream")

    assert [command.command for command in commands] == [CommandName.STOP_STREAM]
    assert commands[0].raw_fragment == "stop stream"


def test_match_select_monitor_from_entities() -> None:
    commands = _match("select monitor two")

    assert commands[0].command == CommandName.SELECT_MONITOR
    assert commands[0].monitor == 2
    assert commands[0].method == MatchMethod.entity_rule
    assert commands[0].confidence == 1.0


def test_match_set_layout_from_entities() -> None:
    commands = _match("primer layout")

    assert [command.command for command in commands] == [CommandName.SET_LAYOUT]
    assert commands[0].layout == 1


def test_match_set_size_from_entities() -> None:
    commands = _match("ponlo en 95 pulgadas")

    assert [command.command for command in commands] == [CommandName.SET_SIZE]
    assert commands[0].size_inches == 95


def test_match_increase_size_relative_phrases() -> None:
    for text in [
        "sube el tamaño",
        "súbele el tamaño",
        "hazlo más grande",
        "hazlo un poco más grande",
    ]:
        commands = _match(text)
        assert [command.command for command in commands] == [CommandName.INCREASE_SIZE]


def test_match_decrease_size_relative_phrases() -> None:
    for text in [
        "bájale el tamaño",
        "hazlo más pequeño",
        "hazlo un poco más pequeño",
    ]:
        commands = _match(text)
        assert [command.command for command in commands] == [CommandName.DECREASE_SIZE]


def test_match_monitor_and_relative_size() -> None:
    commands = _match("agranda la pantalla dos")

    assert [command.command for command in commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.INCREASE_SIZE,
    ]
    assert commands[0].monitor == 2

    commands = _match("reduce el monitor uno")
    assert [command.command for command in commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.DECREASE_SIZE,
    ]
    assert commands[0].monitor == 1


def test_match_set_size_suppresses_relative_size() -> None:
    commands = _match("cambia pantalla dos a 55")

    assert [command.command for command in commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert commands[0].monitor == 2
    assert commands[1].size_inches == 55
    assert CommandName.INCREASE_SIZE not in {command.command for command in commands}
    assert CommandName.DECREASE_SIZE not in {command.command for command in commands}


def test_match_exact_direction_command() -> None:
    commands = _match("izquierda")

    assert [command.command for command in commands] == [CommandName.MOVE_LEFT]
    assert commands[0].method == MatchMethod.exact_rule


def test_match_recenter_suppresses_move_commands() -> None:
    commands = _match("recenter objects left")

    assert [command.command for command in commands] == [CommandName.RECENTER_OBJECTS]


def test_match_multiple_commands_without_duplicates() -> None:
    commands = _match("monitor one left")

    assert [command.command for command in commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.MOVE_LEFT,
    ]


def test_match_show_voice_commands() -> None:
    commands = _match("mostrar comandos de voz")

    assert [command.command for command in commands] == [CommandName.SHOW_VOICE_COMMANDS]


def test_match_open_settings_from_alias() -> None:
    commands = _match("configuracion")

    assert [command.command for command in commands] == [CommandName.OPEN_SETTINGS]


def test_match_stop_active_when_specific_stop_rules_do_not_apply() -> None:
    commands = _match("cancelar")

    assert [command.command for command in commands] == [CommandName.STOP_ACTIVE]


def test_match_stream_when_no_stop_prefix_exists() -> None:
    commands = _match("iniciar stream")

    assert [command.command for command in commands] == [CommandName.START_STREAM]
