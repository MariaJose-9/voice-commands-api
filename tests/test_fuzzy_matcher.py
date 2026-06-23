from app.fuzzy_matcher import get_fuzzy_candidates, match_by_fuzzy
from app.preprocessor import normalize_text
from app.schemas import CommandName, MatchMethod


def test_match_by_fuzzy_does_not_return_entity_only_command_without_entities() -> None:
    command = match_by_fuzzy(normalize_text("monitr one"))
    assert command is None


def test_get_fuzzy_candidates_surfaces_monitor_typo() -> None:
    candidates = get_fuzzy_candidates(normalize_text("monitr one"))
    assert candidates[0]["command"] == CommandName.SELECT_MONITOR.value
    assert candidates[0]["score"] >= 88.0


def test_match_by_fuzzy_voice_commands_typo() -> None:
    command = match_by_fuzzy(normalize_text("voise commands"))
    assert command is not None
    assert command.command == CommandName.SHOW_VOICE_COMMANDS
    assert command.method == MatchMethod.fuzzy
    assert command.raw_fragment == "voise commands"


def test_match_by_fuzzy_stream_typo() -> None:
    command = match_by_fuzzy(normalize_text("stram"))
    assert command is not None
    assert command.command == CommandName.START_STREAM
    assert command.confidence >= 0.88


def test_match_by_fuzzy_recenter_typo() -> None:
    command = match_by_fuzzy(normalize_text("recnter objects"))
    assert command is not None
    assert command.command == CommandName.RECENTER_OBJECTS


def test_match_by_fuzzy_settings_typo() -> None:
    command = match_by_fuzzy(normalize_text("setings"))
    assert command is not None
    assert command.command == CommandName.OPEN_SETTINGS


def test_get_fuzzy_candidates_limit() -> None:
    candidates = get_fuzzy_candidates(normalize_text("voise commands"), limit=3)
    assert len(candidates) == 3
    assert set(candidates[0].keys()) == {"command", "example", "score"}
