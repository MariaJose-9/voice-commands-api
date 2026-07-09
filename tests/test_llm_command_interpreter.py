from __future__ import annotations

import app.ollama_fallback as ollama_fallback
from app.schemas import CommandName, MatchMethod, NormalizedCommand
from app.services.command_spec_service import CommandParameterSpec, CommandSpec
from app.services import size_validation_service


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


class SequentialFakeClient:
    def __init__(self, responses, calls, timeout):
        self.responses = list(responses)
        self.calls = calls
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url, json):
        self.calls.append({"url": url, "json": json, "timeout": self.timeout})
        return self.responses.pop(0)


def _ollama_payload(content: str) -> dict:
    return {"message": {"content": content}}


def test_llm_interpreter_returns_monitor_and_dynamic_set_size(monkeypatch) -> None:
    calls = []
    payload = _ollama_payload(
        """
        {
          "ok": true,
          "commands": [
            {
              "command": "SELECT_MONITOR",
              "monitor": 1,
              "layout": null,
              "size_inches": null,
              "value": null,
              "confidence": 0.95,
              "raw_fragment": "monitor 1"
            },
            {
              "command": "SET_SIZE",
              "monitor": null,
              "layout": null,
              "size_inches": 72,
              "value": null,
              "confidence": 0.95,
              "raw_fragment": "redimensiona a 72 pulgadas"
            }
          ],
          "needs_confirmation": false,
          "message": null
        }
        """
    )
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload), calls, timeout),
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_bool",
        lambda key, default: True,
    )
    monkeypatch.setattr(
        size_validation_service,
        "_get_runtime_int",
        lambda key, default: {"MIN_SIZE_INCHES": 40, "MAX_SIZE_INCHES": 150}[key],
    )

    response = ollama_fallback.interpret_commands_with_llm(
        raw_text="Redimensiona a 72 pulgadas el monitor 1",
        normalized_text="redimensiona a 72 pulgadas el monitor 1",
        language_hint="es",
    )

    assert response is not None
    assert response.needs_confirmation is False
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert response.commands[0].monitor == 1
    assert response.commands[1].size_inches == 72
    assert all(command.method == MatchMethod.llm for command in response.commands)


def test_llm_interpreter_converts_invented_command_to_unknown() -> None:
    response = ollama_fallback.parse_llm_response(
        {
            "ok": True,
            "commands": [
                {
                    "command": "RESIZE_MONITOR",
                    "confidence": 0.9,
                    "raw_fragment": "resize",
                }
            ],
            "needs_confirmation": False,
            "message": None,
        },
        raw_text="resize",
        normalized_text="resize",
    )

    assert response is not None
    assert response.ok is False
    assert response.commands[0].command == CommandName.UNKNOWN


def test_llm_interpreter_rejects_size_outside_configured_range() -> None:
    response = ollama_fallback.parse_llm_response(
        {
            "ok": True,
            "commands": [
                {
                    "command": "SET_SIZE",
                    "size_inches": 151,
                    "confidence": 0.9,
                    "raw_fragment": "151 pulgadas",
                }
            ],
            "needs_confirmation": False,
            "message": None,
        },
        raw_text="151 pulgadas",
        normalized_text="151 pulgadas",
    )

    assert response is None


def test_llm_interpreter_caps_confidence(monkeypatch) -> None:
    monkeypatch.setattr(
        ollama_fallback.runtime_settings_service,
        "get_runtime_float_setting",
        lambda key, default: 0.85 if key == "LLM_CONFIDENCE_CAP" else default,
    )

    response = ollama_fallback.parse_llm_response(
        {
            "ok": True,
            "commands": [
                {
                    "command": "MOVE_RIGHT",
                    "confidence": 0.99,
                    "raw_fragment": "derecha",
                }
            ],
            "needs_confirmation": False,
            "message": None,
        },
        raw_text="derecha",
        normalized_text="derecha",
    )

    assert response is not None
    assert response.commands[0].confidence == 0.85


def test_llm_interpreter_uses_runtime_timeout(monkeypatch) -> None:
    calls = []
    payload = _ollama_payload(
        '{"ok": true, "commands": [{"command": "MOVE_LEFT", "confidence": 0.9, '
        '"raw_fragment": "left"}], "needs_confirmation": false, "message": null}'
    )
    monkeypatch.setattr(
        ollama_fallback.runtime_settings_service,
        "get_runtime_float_setting",
        lambda key, default: 6.5 if key == "OLLAMA_TIMEOUT_SECONDS" else default,
    )
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload), calls, timeout),
    )

    response = ollama_fallback.interpret_commands_with_llm(
        raw_text="left",
        normalized_text="left",
    )

    assert response is not None
    assert calls[0]["timeout"] == 6.5


def test_llm_interpreter_invalid_json_returns_none(monkeypatch) -> None:
    payload = _ollama_payload("not-json")
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload), [], timeout),
    )

    response = ollama_fallback.interpret_commands_with_llm(
        raw_text="weird",
        normalized_text="weird",
    )

    assert response is None


def test_llm_interpreter_parses_pure_json_response(monkeypatch) -> None:
    payload = {
        "ok": True,
        "commands": [
            {
                "command": "MOVE_LEFT",
                "confidence": 0.9,
                "raw_fragment": "left",
            }
        ],
        "needs_confirmation": False,
        "message": None,
    }
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload), [], timeout),
    )

    response = ollama_fallback.interpret_commands_with_llm("left", "left")

    assert response is not None
    assert response.commands[0].command == CommandName.MOVE_LEFT


def test_llm_interpreter_parses_markdown_json_block(monkeypatch) -> None:
    payload = _ollama_payload(
        '```json\n{"ok": true, "commands": [{"command": "MOVE_RIGHT", '
        '"confidence": 0.9, "raw_fragment": "right"}], '
        '"needs_confirmation": false, "message": null}\n```'
    )
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload), [], timeout),
    )

    response = ollama_fallback.interpret_commands_with_llm("right", "right")

    assert response is not None
    assert response.commands[0].command == CommandName.MOVE_RIGHT


def test_llm_interpreter_parses_json_with_surrounding_text(monkeypatch) -> None:
    payload = _ollama_payload(
        'Sure: {"ok": true, "commands": [{"command": "MOVE_UP", '
        '"confidence": 0.9, "raw_fragment": "up"}], '
        '"needs_confirmation": false, "message": null} done.'
    )
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: FakeClient(FakeResponse(payload), [], timeout),
    )

    response = ollama_fallback.interpret_commands_with_llm("up", "up")

    assert response is not None
    assert response.commands[0].command == CommandName.MOVE_UP


def test_llm_interpreter_retries_without_schema_when_format_fails(monkeypatch) -> None:
    calls = []
    success_payload = _ollama_payload(
        '{"ok": true, "commands": [{"command": "MOVE_DOWN", "confidence": 0.9, '
        '"raw_fragment": "down"}], "needs_confirmation": false, "message": null}'
    )
    monkeypatch.setattr(
        ollama_fallback.httpx,
        "Client",
        lambda timeout: SequentialFakeClient(
            [FakeResponse({"error": "format unsupported"}, status_code=400), FakeResponse(success_payload)],
            calls,
            timeout,
        ),
    )

    response = ollama_fallback.interpret_commands_with_llm("down", "down")

    assert response is not None
    assert response.commands[0].command == CommandName.MOVE_DOWN
    assert len(calls) == 2
    assert "format" in calls[0]["json"]
    assert "format" not in calls[1]["json"]


def test_previous_commands_are_included_in_prompt() -> None:
    previous_commands = [
        NormalizedCommand(
            command=CommandName.SELECT_MONITOR,
            confidence=1.0,
            method=MatchMethod.entity_rule,
            monitor=1,
            raw_fragment="monitor 1",
        )
    ]

    prompt = ollama_fallback.build_llm_command_prompt(
        raw_text="redimensiona a 72 pulgadas el monitor 1",
        normalized_text="redimensiona a 72 pulgadas el monitor 1",
        previous_commands=previous_commands,
        completeness_reason="explicit_size_intent_missing_set_size",
    )

    assert "previous_commands" in prompt
    assert "SELECT_MONITOR" in prompt
    assert "explicit_size_intent_missing_set_size" in prompt


def test_llm_set_size_with_monitor_is_canonicalized(monkeypatch) -> None:
    response = ollama_fallback.parse_llm_response(
        {
            "ok": True,
            "commands": [
                {
                    "command": "SET_SIZE",
                    "monitor": 2,
                    "size_inches": 75,
                    "confidence": 0.9,
                    "raw_fragment": "monitor 2 en 75 pulgadas",
                }
            ],
            "needs_confirmation": False,
            "message": None,
        },
        raw_text="Necesito que el monitor 2 este en 75 pulgadas",
        normalized_text="necesito que el monitor 2 este en 75 pulgadas",
        language_hint="es",
    )

    assert response is not None
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert response.commands[0].monitor == 2
    assert response.commands[0].method == MatchMethod.llm
    assert response.commands[1].monitor is None
    assert response.commands[1].size_inches == 75


def test_llm_prompt_includes_monitor_target_canonicalization_rule() -> None:
    prompt = ollama_fallback.build_llm_command_prompt(
        raw_text="Necesito que el monitor 2 este en 75 pulgadas",
        normalized_text="necesito que el monitor 2 este en 75 pulgadas",
    )

    assert "Do not attach monitor to SET_SIZE" in prompt
    assert "SELECT_MONITOR" in prompt
    assert "Necesito que el monitor 2 este en 75 pulgadas" in prompt
    assert '"SET_SIZE","monitor":2,"size_inches":75' in prompt


def test_llm_prompt_contains_custom_active_command(monkeypatch) -> None:
    monkeypatch.setattr(
        ollama_fallback,
        "get_active_command_specs",
        lambda: [
            CommandSpec(
                code="ROTATE_SCREEN",
                display_name="Rotate Screen",
                description="rotate selected screen",
                command_type="custom",
                status="active",
                client_action_key="rotate_screen",
                examples=[
                    "rota el monitor 2 noventa grados",
                    "gira la pantalla dos a 90 grados",
                ],
                parameters=[
                    CommandParameterSpec(
                        slot_name="monitor",
                        entity_code="monitor",
                        target_field="monitor",
                        required=False,
                        allow_multiple=False,
                        data_type="enum",
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
        ],
    )

    prompt = ollama_fallback.build_llm_command_prompt(
        raw_text="rota el monitor 2 noventa grados",
        normalized_text="rota el monitor 2 noventa grados",
    )

    assert "ROTATE_SCREEN" in prompt
    assert '"command_type": "custom"' in prompt
    assert '"client_action_key": "rotate_screen"' in prompt
    assert "rotate selected screen" in prompt
    assert "rota el monitor 2 noventa grados" in prompt


def test_llm_prompt_contains_custom_parameters(monkeypatch) -> None:
    monkeypatch.setattr(
        ollama_fallback,
        "get_active_command_specs",
        lambda: [
            CommandSpec(
                code="ROTATE_SCREEN",
                display_name="Rotate Screen",
                command_type="custom",
                status="active",
                client_action_key="rotate_screen",
                parameters=[
                    CommandParameterSpec(
                        slot_name="angle",
                        entity_code="angle_degrees",
                        target_field="angle",
                        required=True,
                        allow_multiple=False,
                        description="Rotation angle.",
                        extraction_hint="Extract degrees from the utterance.",
                        data_type="integer",
                        unit="degrees",
                        dynamic_values=True,
                        min_value=0,
                        max_value=360,
                    ),
                ],
            )
        ],
    )

    prompt = ollama_fallback.build_llm_command_prompt(
        raw_text="gira 90 grados",
        normalized_text="gira 90 grados",
    )

    assert '"slot_name": "angle"' in prompt
    assert '"entity": "angle_degrees"' in prompt
    assert '"target_field": "angle"' in prompt
    assert '"required": true' in prompt
    assert '"data_type": "integer"' in prompt
    assert '"unit": "degrees"' in prompt
    assert '"min_value": 0.0' in prompt
    assert '"max_value": 360.0' in prompt
    assert "Extract degrees from the utterance." in prompt


def test_llm_prompt_does_not_contain_disabled_command(monkeypatch) -> None:
    monkeypatch.setattr(
        ollama_fallback,
        "get_active_command_specs",
        lambda: [
            CommandSpec(
                code="ACTIVE_CUSTOM",
                display_name="Active Custom",
                command_type="custom",
                status="active",
                client_action_key="active_custom",
            )
        ],
    )

    prompt = ollama_fallback.build_llm_command_prompt(
        raw_text="test",
        normalized_text="test",
    )

    assert "ACTIVE_CUSTOM" in prompt
    assert "DISABLED_CUSTOM" not in prompt


def test_llm_canonicalization_does_not_duplicate_existing_select_monitor() -> None:
    response = ollama_fallback.parse_llm_response(
        {
            "ok": True,
            "commands": [
                {
                    "command": "SELECT_MONITOR",
                    "monitor": 2,
                    "confidence": 0.95,
                    "raw_fragment": "monitor 2",
                },
                {
                    "command": "SET_SIZE",
                    "monitor": 2,
                    "size_inches": 75,
                    "confidence": 0.9,
                    "raw_fragment": "75 pulgadas",
                },
            ],
            "needs_confirmation": False,
            "message": None,
        },
        raw_text="Necesito que el monitor 2 este en 75 pulgadas",
        normalized_text="necesito que el monitor 2 este en 75 pulgadas",
        language_hint="es",
    )

    assert response is not None
    assert [command.command for command in response.commands] == [
        CommandName.SELECT_MONITOR,
        CommandName.SET_SIZE,
    ]
    assert len(
        [
            command
            for command in response.commands
            if command.command == CommandName.SELECT_MONITOR
        ]
    ) == 1
    assert response.commands[0].monitor == 2
    assert response.commands[1].monitor is None
    assert response.commands[1].size_inches == 75
