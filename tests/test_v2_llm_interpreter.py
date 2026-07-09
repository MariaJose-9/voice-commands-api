from __future__ import annotations

import json

import app.v2.llm_interpreter as llm_interpreter
from app.services.command_spec_service import CommandParameterSpec, CommandSpec


class FakeResponse:
    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, response, calls, timeout):
        self.response = response
        self.calls = calls
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        self.calls.append({"url": url, "json": json, "timeout": self.timeout})
        return self.response


def _rotate_spec() -> CommandSpec:
    return CommandSpec(
        code="ROTATE_SCREEN",
        display_name="Rotate Screen",
        command_type="custom",
        status="active",
        enabled=True,
        protected=False,
        client_action_key="rotate_screen",
        examples=["rota el monitor dos noventa grados"],
        parameters=[
            CommandParameterSpec(
                slot_name="monitor",
                entity_code="monitor",
                target_field="monitor",
                required=False,
                allow_multiple=False,
                data_type="integer",
            ),
            CommandParameterSpec(
                slot_name="angle",
                entity_code="angle_degrees",
                target_field="angle",
                required=True,
                allow_multiple=False,
                data_type="integer",
                unit="degrees",
                dynamic_values=True,
                min_value=0,
                max_value=360,
            ),
        ],
    )


def _ollama_payload(content: dict) -> dict:
    return {"message": {"content": json.dumps(content)}}


def test_v2_llm_returns_valid_rotate_screen(monkeypatch) -> None:
    calls = []
    payload = _ollama_payload(
        {
            "commands": [
                {
                    "code": "ROTATE_SCREEN",
                    "params": {"monitor": 2, "angle": 90},
                    "confidence": 0.92,
                    "raw_fragment": "rota el monitor 2 noventa grados",
                }
            ],
            "needs_confirmation": False,
        }
    )
    monkeypatch.setattr(
        llm_interpreter.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload), calls, timeout),
    )

    commands, needs_confirmation = llm_interpreter.interpret_dynamic_commands_with_llm(
        raw_text="rota el monitor 2 noventa grados",
        normalized_text="rota el monitor 2 noventa grados",
        specs=[_rotate_spec()],
        client_capabilities=["rotate_screen"],
    )

    assert needs_confirmation is False
    assert len(commands) == 1
    assert commands[0].code == "ROTATE_SCREEN"
    assert commands[0].type == "custom"
    assert commands[0].client_action_key == "rotate_screen"
    assert commands[0].params == {"monitor": 2, "angle": 90}
    assert calls[0]["json"]["format"]["properties"]["commands"]["items"]["properties"]["code"]["enum"] == [
        "ROTATE_SCREEN"
    ]


def test_v2_llm_rejects_unknown_custom_code() -> None:
    commands, needs_confirmation = llm_interpreter.parse_v2_llm_response(
        {
            "commands": [
                {
                    "code": "UNKNOWN_CUSTOM",
                    "params": {"angle": 90},
                    "confidence": 0.9,
                    "raw_fragment": "unknown",
                }
            ],
            "needs_confirmation": False,
        },
        specs=[_rotate_spec()],
        client_capabilities=["rotate_screen"],
    )

    assert commands == []
    assert needs_confirmation is True


def test_v2_llm_rejects_rotate_without_required_angle() -> None:
    commands, needs_confirmation = llm_interpreter.parse_v2_llm_response(
        {
            "commands": [
                {
                    "code": "ROTATE_SCREEN",
                    "params": {"monitor": 2},
                    "confidence": 0.9,
                    "raw_fragment": "rota monitor dos",
                }
            ],
            "needs_confirmation": False,
        },
        specs=[_rotate_spec()],
        client_capabilities=["rotate_screen"],
    )

    assert commands == []
    assert needs_confirmation is True


def test_v2_llm_accepts_angle_90_params() -> None:
    commands, needs_confirmation = llm_interpreter.parse_v2_llm_response(
        {
            "commands": [
                {
                    "code": "ROTATE_SCREEN",
                    "params": {"angle": 90},
                    "confidence": 0.9,
                    "raw_fragment": "rota noventa grados",
                }
            ],
            "needs_confirmation": False,
        },
        specs=[_rotate_spec()],
        client_capabilities=["rotate_screen"],
    )

    assert needs_confirmation is False
    assert commands[0].params == {"angle": 90}


def test_v2_llm_uses_client_action_key_from_spec() -> None:
    commands, _needs_confirmation = llm_interpreter.parse_v2_llm_response(
        {
            "commands": [
                {
                    "code": "ROTATE_SCREEN",
                    "params": {"angle": 90},
                    "confidence": 0.9,
                    "raw_fragment": "rota noventa grados",
                }
            ],
            "needs_confirmation": False,
        },
        specs=[_rotate_spec()],
        client_capabilities=["rotate_screen"],
    )

    assert commands[0].client_action_key == "rotate_screen"
