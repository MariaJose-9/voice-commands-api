#!/usr/bin/env python
"""Generate a lightweight NLU coverage report for command normalization."""

from __future__ import annotations

import json
import argparse
from collections import defaultdict
import logging
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


FIXTURE_PATH = ROOT_DIR / "tests" / "fixtures" / "command_phrases.json"
PRODUCTION_FIXTURE_PATH = ROOT_DIR / "tests" / "fixtures" / "production_natural_phrases.json"
CATALOG_PATH = ROOT_DIR / "app" / "commands" / "catalog.yml"

CRITICAL_PHRASES: list[dict[str, Any]] = [
    {
        "text": "pon pantalla 2 en 55",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 2},
            {"command": "SET_SIZE", "size_inches": 55},
        ],
    },
    {
        "text": "cambia la pantalla dos a 55",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 2},
            {"command": "SET_SIZE", "size_inches": 55},
        ],
    },
    {
        "text": "haz la pantalla de 55 pulgadas",
        "expected": [{"command": "SET_SIZE", "size_inches": 55}],
    },
    {
        "text": "configura monitor dos tamaño 65",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 2},
            {"command": "SET_SIZE", "size_inches": 65},
        ],
    },
    {
        "text": "sube el tamaño",
        "expected": [{"command": "INCREASE_SIZE"}],
    },
    {
        "text": "súbele el tamaño",
        "expected": [{"command": "INCREASE_SIZE"}],
    },
    {
        "text": "bájale el tamaño",
        "expected": [{"command": "DECREASE_SIZE"}],
    },
    {
        "text": "hazlo más grande",
        "expected": [{"command": "INCREASE_SIZE"}],
    },
    {
        "text": "hazlo un poco más pequeño",
        "expected": [{"command": "DECREASE_SIZE"}],
    },
    {
        "text": "agranda la pantalla dos",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 2},
            {"command": "INCREASE_SIZE"},
        ],
    },
    {
        "text": "reduce el monitor uno",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 1},
            {"command": "DECREASE_SIZE"},
        ],
    },
    {
        "text": "pantalla una a la izquierda",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 1},
            {"command": "MOVE_LEFT"},
        ],
    },
    {
        "text": "pantalla dos a la derecha",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 2},
            {"command": "MOVE_RIGHT"},
        ],
    },
    {
        "text": "coja la pantalla una y mueve la licuada",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 1},
            {"command": "MOVE_LEFT"},
        ],
    },
    {
        "text": "pantalla 2 mueve la la derecha y luego las es en el tamaño de 55 puladas",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 2},
            {"command": "MOVE_RIGHT"},
            {"command": "SET_SIZE", "size_inches": 55},
        ],
    },
    {
        "text": "pon el monitor dos en sesenta y cinco pulgadas",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 2},
            {"command": "SET_SIZE", "size_inches": 65},
        ],
    },
    {
        "text": "cambia pantalla uno a ciento veinte pulgadas",
        "expected": [
            {"command": "SELECT_MONITOR", "monitor": 1},
            {"command": "SET_SIZE", "size_inches": 120},
        ],
    },
    {
        "text": "abre comandos de voz",
        "expected": [{"command": "SHOW_VOICE_COMMANDS"}],
    },
    {
        "text": "cierra comandos de voz",
        "expected": [{"command": "CLOSE_VOICE_COMMANDS"}],
    },
    {
        "text": "detén stream",
        "expected": [{"command": "STOP_STREAM"}],
    },
]


def _load_json_fixture(path: Path) -> list[dict[str, Any]]:
    """Load command phrase fixtures if available."""

    if not path.exists():
        return []
    return json.loads(path.read_text(encoding="utf-8"))


def _load_catalog(path: Path) -> dict[str, Any]:
    """Load the YAML command catalog."""

    if not path.exists():
        return {"commands": []}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {"commands": []}


def _count_examples_by_command(catalog: dict[str, Any]) -> dict[str, int]:
    """Return example counts per command from catalog.yml."""

    counts: dict[str, int] = {}
    for item in catalog.get("commands", []):
        command = str(item.get("command", "UNKNOWN"))
        examples = item.get("examples") or []
        counts[command] = len(examples) if isinstance(examples, list) else 0
    return counts


def _command_to_dict(command: Any) -> dict[str, Any]:
    """Serialize a NormalizedCommand with only fields useful for this report."""

    payload = command.model_dump(mode="json")
    return {
        key: payload.get(key)
        for key in ("command", "monitor", "layout", "size_inches", "confidence", "method")
        if payload.get(key) is not None
    }


def _matches_expected(actual: dict[str, Any], expected: dict[str, Any]) -> bool:
    """Return True when actual command satisfies the expected command subset."""

    if actual.get("command") != expected.get("command"):
        return False
    for key in ("monitor", "layout", "size_inches"):
        if key in expected and actual.get(key) != expected[key]:
            return False
    return True


def _missing_expected(
    actual_commands: list[dict[str, Any]],
    expected_commands: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return expected commands that were not found in actual output."""

    missing: list[dict[str, Any]] = []
    for expected in expected_commands:
        if not any(_matches_expected(actual, expected) for actual in actual_commands):
            missing.append(expected)
    return missing


def _has_missing_entity(expected: dict[str, Any], actual_commands: list[dict[str, Any]]) -> bool:
    """Return True when command exists but a required expected entity differs."""

    entity_keys = ("monitor", "layout", "size_inches")
    if not any(key in expected for key in entity_keys):
        return False

    for actual in actual_commands:
        if actual.get("command") != expected.get("command"):
            continue
        if any(key in expected and actual.get(key) != expected[key] for key in entity_keys):
            return True
    return False


def _run_phrase_checks(phrases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize phrases and return per-phrase result rows."""

    from app.normalizer import normalize_command_text

    rows: list[dict[str, Any]] = []
    for item in phrases:
        response = normalize_command_text(item["text"], language_hint="es")
        actual_commands = [_command_to_dict(command) for command in response.commands]
        missing = _missing_expected(actual_commands, item["expected"])
        unknown = any(command.get("command") == "UNKNOWN" for command in actual_commands)
        missing_entities = [
            expected
            for expected in item["expected"]
            if _has_missing_entity(expected, actual_commands)
        ]
        rows.append(
            {
                "text": item["text"],
                "ok": not missing and not unknown,
                "expected": item["expected"],
                "actual": actual_commands,
                "missing": missing,
                "missing_entities": missing_entities,
                "unknown": unknown,
                "needs_confirmation": response.needs_confirmation,
            }
        )
    return rows


def _criticality_score(row: dict[str, Any]) -> int:
    """Rank failures by severity for report display."""

    score = 0
    if row["unknown"]:
        score += 100
    score += len(row["missing"]) * 20
    score += len(row["missing_entities"]) * 10
    if row["needs_confirmation"]:
        score += 5
    return score


def _parse_args() -> argparse.Namespace:
    """Parse command-line options for report execution."""

    parser = argparse.ArgumentParser(
        description="Generate an NLU coverage report for critical command phrases."
    )
    parser.add_argument(
        "--semantic",
        action="store_true",
        help=(
            "Enable semantic matcher during the report. By default it is disabled "
            "to avoid model downloads and keep the report deterministic."
        ),
    )
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help=(
            "Path to a JSON fixture with text/expected entries. "
            "Example: tests/fixtures/production_natural_phrases.json"
        ),
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=None,
        help="Minimum required coverage percentage. Exits with code 1 if unmet.",
    )
    return parser.parse_args()


def main() -> int:
    """Print NLU catalog and critical phrase coverage."""

    args = _parse_args()
    logging.basicConfig(level=logging.CRITICAL)
    if not args.semantic:
        os.environ["ENABLE_SEMANTIC_MATCHER"] = "false"
    os.environ.setdefault("ENABLE_OLLAMA_FALLBACK", "false")

    selected_fixture_path = (
        args.fixture if args.fixture is not None else None
    )
    if selected_fixture_path is not None and not selected_fixture_path.is_absolute():
        selected_fixture_path = ROOT_DIR / selected_fixture_path

    fixture_items = (
        _load_json_fixture(selected_fixture_path)
        if selected_fixture_path is not None
        else CRITICAL_PHRASES
    )
    catalog = _load_catalog(CATALOG_PATH)
    example_counts = _count_examples_by_command(catalog)
    undercovered = {
        command: count
        for command, count in sorted(example_counts.items(), key=lambda item: (item[1], item[0]))
        if count < 20
    }
    results = _run_phrase_checks(fixture_items)
    failures = [item for item in results if not item["ok"]]
    successes = len(results) - len(failures)
    coverage = (successes / len(results) * 100.0) if results else 0.0
    unknown_rows = [item for item in results if item["unknown"]]
    confirmation_rows = [item for item in results if item["needs_confirmation"]]
    missing_entity_rows = [item for item in results if item["missing_entities"]]
    failures_by_command: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for failure in failures:
        for missing in failure["missing"]:
            failures_by_command[str(missing.get("command", "UNKNOWN"))].append(failure)

    print("NLU Coverage Report")
    print("===================")
    print(f"Fixture path: {selected_fixture_path or 'built-in critical phrases'}")
    print(f"Fixture phrases loaded: {len(fixture_items)}")
    print(f"Catalog path: {CATALOG_PATH}")
    print(f"Catalog commands: {len(example_counts)}")
    print(f"Semantic matcher enabled: {args.semantic}")
    if args.min_coverage is not None:
        print(f"Minimum coverage required: {args.min_coverage:.2f}%")
    print()

    print("Examples per command")
    print("--------------------")
    for command, count in sorted(example_counts.items()):
        print(f"{command}: {count}")
    print()

    print("Commands with fewer than 20 examples")
    print("------------------------------------")
    if undercovered:
        for command, count in undercovered.items():
            print(f"{command}: {count}")
    else:
        print("None")
    print()

    print("Phrase checks")
    print("-------------")
    print(f"Total tested: {len(results)}")
    print(f"Passed: {successes}")
    print(f"Failed: {len(failures)}")
    print(f"Coverage: {coverage:.2f}%")
    print(f"UNKNOWN results: {len(unknown_rows)}")
    print(f"Needs confirmation: {len(confirmation_rows)}")
    print(f"Missing important entities: {len(missing_entity_rows)}")
    print()

    print("Failures by expected command")
    print("----------------------------")
    if failures_by_command:
        for command, rows in sorted(failures_by_command.items()):
            print(f"{command}: {len(rows)}")
    else:
        print("None")
    print()

    if unknown_rows:
        print("Phrases returning UNKNOWN")
        print("-------------------------")
        for row in unknown_rows[:20]:
            print(f"- {row['text']}")
        print()

    if confirmation_rows:
        print("Phrases needing confirmation")
        print("----------------------------")
        for row in confirmation_rows[:20]:
            print(f"- {row['text']}")
        print()

    if missing_entity_rows:
        print("Phrases missing important entities")
        print("----------------------------------")
        for row in missing_entity_rows[:20]:
            print(f"- {row['text']}: {json.dumps(row['missing_entities'], ensure_ascii=False)}")
        print()

    if failures:
        print("Top 20 critical failures")
        print("------------------------")
        for failure in sorted(failures, key=_criticality_score, reverse=True)[:20]:
            print(f"Phrase: {failure['text']}")
            print(f"Expected: {json.dumps(failure['expected'], ensure_ascii=False)}")
            print(f"Actual: {json.dumps(failure['actual'], ensure_ascii=False)}")
            print(f"Missing: {json.dumps(failure['missing'], ensure_ascii=False)}")
            if failure["missing_entities"]:
                print(
                    "Missing entities: "
                    f"{json.dumps(failure['missing_entities'], ensure_ascii=False)}"
                )
            print(f"UNKNOWN: {failure['unknown']}")
            print(f"Needs confirmation: {failure['needs_confirmation']}")
            print()
    else:
        print("All phrases passed.")

    if args.min_coverage is not None and coverage < args.min_coverage:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
