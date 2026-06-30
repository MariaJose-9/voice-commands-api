from __future__ import annotations

import json
from pathlib import Path

import app.normalizer as normalizer_module
from app.normalizer import normalize_command_text
from app.schemas import CommandName


FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "production_natural_phrases.json"
)


def _matches_expected(actual: dict, expected: dict) -> bool:
    if actual["command"] != expected["command"]:
        return False

    for key in ("monitor", "layout", "size_inches"):
        if key in expected and actual.get(key) != expected[key]:
            return False

    return True


def test_production_natural_phrases_fixture_has_minimum_size() -> None:
    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert len(payload) >= 350


def test_production_natural_phrases_match_expected_commands(monkeypatch) -> None:
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

    payload = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    failures: list[str] = []

    for item in payload:
        response = normalize_command_text(item["text"])
        actual_commands = [command.model_dump(mode="json") for command in response.commands]
        actual_names = [command["command"] for command in actual_commands]

        if CommandName.UNKNOWN.value in actual_names:
            failures.append(
                f"text={item['text']!r} returned UNKNOWN actual={actual_commands!r}"
            )
            continue

        for expected in item["expected"]:
            if not any(_matches_expected(actual, expected) for actual in actual_commands):
                failures.append(
                    f"text={item['text']!r} missing expected={expected!r} "
                    f"actual={actual_commands!r}"
                )

    assert not failures, "\n".join(failures[:50])
