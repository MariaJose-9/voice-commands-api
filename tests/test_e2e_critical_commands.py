from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.schemas import CommandName


client = TestClient(app)


CRITICAL_CASES = [
    (
        "pon pantalla 2 en 55",
        [
            {"command": CommandName.SELECT_MONITOR.value, "monitor": 2},
            {"command": CommandName.SET_SIZE.value, "size_inches": 55},
        ],
    ),
    (
        "pantalla 2 mueve la la derecha y luego las es en el tamaño de 55 puladas",
        [
            {"command": CommandName.SELECT_MONITOR.value, "monitor": 2},
            {"command": CommandName.MOVE_RIGHT.value},
            {"command": CommandName.SET_SIZE.value, "size_inches": 55},
        ],
    ),
    (
        "coja la pantalla una y mueve la licuada",
        [
            {"command": CommandName.SELECT_MONITOR.value, "monitor": 1},
            {"command": CommandName.MOVE_LEFT.value},
        ],
    ),
    (
        "hazlo un poco más grande",
        [{"command": CommandName.INCREASE_SIZE.value}],
    ),
    (
        "bájale el tamaño",
        [{"command": CommandName.DECREASE_SIZE.value}],
    ),
    (
        "pon el monitor dos en sesenta y cinco pulgadas",
        [
            {"command": CommandName.SELECT_MONITOR.value, "monitor": 2},
            {"command": CommandName.SET_SIZE.value, "size_inches": 65},
        ],
    ),
    (
        "cambia pantalla uno a ciento veinte pulgadas",
        [
            {"command": CommandName.SELECT_MONITOR.value, "monitor": 1},
            {"command": CommandName.SET_SIZE.value, "size_inches": 120},
        ],
    ),
    (
        "abre comandos de voz",
        [{"command": CommandName.SHOW_VOICE_COMMANDS.value}],
    ),
    (
        "detén stream",
        [{"command": CommandName.STOP_STREAM.value}],
    ),
]


def _assert_expected_commands(actual: list[dict], expected: list[dict]) -> None:
    actual_commands = [item["command"] for item in actual]
    assert CommandName.UNKNOWN.value not in actual_commands

    for expected_command in expected:
        matches = [
            command
            for command in actual
            if command["command"] == expected_command["command"]
        ]
        assert matches, {
            "missing": expected_command,
            "actual": actual,
        }

        for entity_key in ("monitor", "layout", "size_inches"):
            if entity_key not in expected_command:
                continue
            assert any(
                command.get(entity_key) == expected_command[entity_key]
                for command in matches
            ), {
                "missing_entity": expected_command,
                "actual_matches": matches,
            }


def test_e2e_critical_command_normalization() -> None:
    for text, expected in CRITICAL_CASES:
        response = client.post(
            "/v1/commands/normalize",
            json={"text": text, "language_hint": "es"},
        )

        assert response.status_code == 200, text
        payload = response.json()
        assert payload["ok"] is True, payload
        _assert_expected_commands(payload["commands"], expected)
