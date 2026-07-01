from __future__ import annotations

import app.ollama_fallback as ollama_fallback
from app.schemas import CommandName
from app.services import size_validation_service


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self) -> dict:
        return self._payload


class FakeClient:
    def __init__(self, payload: dict):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, url, json):
        return FakeResponse(self.payload)


def _ollama_payload(content) -> dict:
    if isinstance(content, dict):
        return content
    return {"message": {"content": content}}


def _patch_ollama_payload(monkeypatch, content) -> None:
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(_ollama_payload(content)),
    )


def _patch_dynamic_sizes(monkeypatch) -> None:
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True if key == "ALLOW_DYNAMIC_SIZE_INCHES" else default,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {
            "MIN_SIZE_INCHES": 40,
            "MAX_SIZE_INCHES": 150,
        }.get(key, default),
    )


def _interpret(monkeypatch, content):
    _patch_ollama_payload(monkeypatch, content)
    return ollama_fallback.interpret_commands_with_llm(
        raw_text="Redimensiona a 72 pulgadas el monitor 1",
        normalized_text="redimensiona a 72 pulgadas el monitor 1",
        language_hint="es",
    )


def test_llm_json_contract_accepts_valid_json(monkeypatch) -> None:
    _patch_dynamic_sizes(monkeypatch)
    response = _interpret(
        monkeypatch,
        {
            "ok": True,
            "commands": [
                {"command": "SELECT_MONITOR", "monitor": 1, "confidence": 0.95},
                {"command": "SET_SIZE", "size_inches": 72, "confidence": 0.95},
            ],
            "needs_confirmation": False,
        },
    )

    assert response is not None
    assert response.ok is True
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert response.commands[0].monitor == 1
    assert response.commands[1].size_inches == 72


def test_llm_json_contract_invalid_command_does_not_break(monkeypatch) -> None:
    response = _interpret(
        monkeypatch,
        {
            "ok": True,
            "commands": [{"command": "RESIZE_MONITOR"}],
            "needs_confirmation": False,
        },
    )

    assert response is not None
    assert response.ok is False
    assert response.commands[0].command == CommandName.UNKNOWN


def test_llm_json_contract_rejects_size_outside_range(monkeypatch) -> None:
    _patch_dynamic_sizes(monkeypatch)
    response = _interpret(
        monkeypatch,
        {
            "ok": True,
            "commands": [
                {"command": "SET_SIZE", "size_inches": 500, "confidence": 0.95}
            ],
            "needs_confirmation": False,
        },
    )

    assert response is None


def test_llm_json_contract_rejects_invalid_monitor(monkeypatch) -> None:
    response = _interpret(
        monkeypatch,
        {
            "ok": True,
            "commands": [
                {"command": "SELECT_MONITOR", "monitor": 3, "confidence": 0.95}
            ],
            "needs_confirmation": False,
        },
    )

    assert response is None


def test_llm_json_contract_defaults_missing_confidence(monkeypatch) -> None:
    response = _interpret(
        monkeypatch,
        {
            "ok": True,
            "commands": [{"command": "MOVE_RIGHT", "raw_fragment": "derecha"}],
            "needs_confirmation": False,
        },
    )

    assert response is not None
    assert response.commands[0].command == CommandName.MOVE_RIGHT
    assert response.commands[0].confidence == 0.80


def test_llm_json_contract_parses_markdown_json_block(monkeypatch) -> None:
    _patch_dynamic_sizes(monkeypatch)
    response = _interpret(
        monkeypatch,
        """```json
{
  "ok": true,
  "commands": [
    {"command": "SELECT_MONITOR", "monitor": 1, "confidence": 0.95},
    {"command": "SET_SIZE", "size_inches": 72, "confidence": 0.95}
  ],
  "needs_confirmation": false
}
```""",
    )

    assert response is not None
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]


def test_llm_json_contract_non_json_text_returns_none(monkeypatch) -> None:
    response = _interpret(monkeypatch, "this is not json")

    assert response is None
