from __future__ import annotations

import json
from pathlib import Path

from app.normalizer import normalize_command_text


FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "command_phrases.json"


def _matches_expected(actual: dict, expected: dict) -> bool:
    if actual["command"] != expected["command"]:
        return False

    for key in ("monitor", "layout", "size_inches"):
        if key in expected and actual.get(key) != expected[key]:
            return False

    return True


def test_command_phrases_fixture_covers_minimum_size() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(payload) >= 100


def test_command_phrases_fixture_matches_expected_commands() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))

    for item in payload:
        response = normalize_command_text(item["text"])
        actual_commands = [command.model_dump(mode="json") for command in response.commands]

        for expected in item["expected"]:
            assert any(
                _matches_expected(actual, expected) for actual in actual_commands
            ), (
                f"Missing expected command for text={item['text']!r}. "
                f"Expected={expected!r}, actual={actual_commands!r}"
            )
