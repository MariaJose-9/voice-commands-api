import app.fuzzy_matcher as fuzzy_matcher
import pytest
from app.preprocessor import normalize_text
from app.schemas import CommandName, MatchMethod


@pytest.fixture(autouse=True)
def reset_fuzzy_cache():
    fuzzy_matcher.clear_fuzzy_cache()
    yield
    fuzzy_matcher.clear_fuzzy_cache()


def test_match_by_fuzzy_does_not_return_entity_only_command_without_entities() -> None:
    command = fuzzy_matcher.match_by_fuzzy(normalize_text("mntor one"))
    assert command is None


def test_get_fuzzy_candidates_surfaces_monitor_typo() -> None:
    candidates = fuzzy_matcher.get_fuzzy_candidates(normalize_text("monitr one"))
    assert candidates[0]["command"] == CommandName.SELECT_MONITOR.value
    assert candidates[0]["score"] >= 88.0


def test_match_by_fuzzy_voice_commands_typo() -> None:
    command = fuzzy_matcher.match_by_fuzzy(normalize_text("voise commands"))
    assert command is not None
    assert command.command == CommandName.SHOW_VOICE_COMMANDS
    assert command.method == MatchMethod.fuzzy
    assert command.raw_fragment == "voise commands"


def test_match_by_fuzzy_stream_typo() -> None:
    command = fuzzy_matcher.match_by_fuzzy(normalize_text("stram"))
    assert command is not None
    assert command.command == CommandName.START_STREAM
    assert command.confidence >= 0.88


def test_match_by_fuzzy_recenter_typo() -> None:
    command = fuzzy_matcher.match_by_fuzzy(normalize_text("recnter objects"))
    assert command is not None
    assert command.command == CommandName.RECENTER_OBJECTS


def test_match_by_fuzzy_settings_typo() -> None:
    command = fuzzy_matcher.match_by_fuzzy(normalize_text("setings"))
    assert command is not None
    assert command.command == CommandName.OPEN_SETTINGS


def test_get_fuzzy_candidates_limit() -> None:
    candidates = fuzzy_matcher.get_fuzzy_candidates(normalize_text("voise commands"), limit=3)
    assert len(candidates) == 3
    assert set(candidates[0].keys()) == {"command", "example", "score"}


def test_clear_fuzzy_cache_reloads_updated_catalog(monkeypatch) -> None:
    catalog_state = [
        {
            "command": "START_STREAM",
            "examples": ["start stream"],
        }
    ]

    monkeypatch.setattr(
        fuzzy_matcher,
        "get_active_catalog",
        lambda: catalog_state,
    )
    monkeypatch.setattr(
        fuzzy_matcher,
        "clear_catalog_cache",
        lambda: None,
    )

    fuzzy_matcher.clear_fuzzy_cache()
    initial_match = fuzzy_matcher.match_by_fuzzy(normalize_text("broadcast now"), threshold=80.0)
    assert initial_match is None

    catalog_state = [
        {
            "command": "START_STREAM",
            "examples": ["start stream", "broadcast now"],
        }
    ]

    cached_match = fuzzy_matcher.match_by_fuzzy(normalize_text("broadcast now"), threshold=80.0)
    assert cached_match is None

    fuzzy_matcher.clear_fuzzy_cache()
    refreshed_match = fuzzy_matcher.match_by_fuzzy(
        normalize_text("broadcast now"),
        threshold=80.0,
    )
    assert refreshed_match is not None
    assert refreshed_match.command == CommandName.START_STREAM
