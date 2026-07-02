"""Local LLM command interpreter backed by Ollama."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional

import httpx

from app import config
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand
from app.services import runtime_settings_service
from app.services.command_canonicalization_service import canonicalize_commands


logger = logging.getLogger(__name__)


def _command_names() -> list[str]:
    """Return the list of valid canonical command names."""

    return [command.value for command in CommandName]


def _runtime_str(key: str, default: str) -> str:
    return runtime_settings_service.get_runtime_str_setting(key, default)


def _runtime_float(key: str, default: float) -> float:
    return runtime_settings_service.get_runtime_float_setting(key, default)


def _confidence_cap() -> float:
    return max(0.0, min(1.0, _runtime_float("LLM_CONFIDENCE_CAP", config.LLM_CONFIDENCE_CAP)))


def _accept_threshold() -> float:
    return max(0.0, min(1.0, _runtime_float("LLM_ACCEPT_THRESHOLD", config.LLM_ACCEPT_THRESHOLD)))


def _ollama_timeout_seconds() -> float:
    return max(0.1, _runtime_float("OLLAMA_TIMEOUT_SECONDS", config.OLLAMA_TIMEOUT_SECONDS))


def build_llm_json_schema() -> dict[str, Any]:
    """Return the strict JSON schema expected from the LLM."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["ok", "commands", "needs_confirmation", "message"],
        "properties": {
            "ok": {"type": "boolean"},
            "needs_confirmation": {"type": "boolean"},
            "message": {"type": ["string", "null"]},
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "command",
                        "monitor",
                        "layout",
                        "size_inches",
                        "value",
                        "confidence",
                        "raw_fragment",
                    ],
                    "properties": {
                        "command": {"type": "string", "enum": _command_names()},
                        "monitor": {"type": ["integer", "null"]},
                        "layout": {"type": ["integer", "null"]},
                        "size_inches": {"type": ["integer", "null"]},
                        "value": {"type": ["string", "null"]},
                        "confidence": {"type": ["number", "null"]},
                        "raw_fragment": {"type": ["string", "null"]},
                    },
                },
            },
        },
    }


def _commands_for_prompt(commands: Optional[list[NormalizedCommand]]) -> list[dict[str, Any]]:
    if not commands:
        return []
    return [command.model_dump(mode="json") for command in commands]


def build_llm_command_prompt(
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str] = None,
    context: Optional[dict] = None,
    previous_commands: Optional[list[NormalizedCommand]] = None,
    completeness_reason: Optional[str] = None,
) -> str:
    """Build a strict prompt for command interpretation."""

    payload = {
        "language_hint": language_hint,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "context": context or {},
        "previous_commands": _commands_for_prompt(previous_commands),
        "completeness_reason": completeness_reason,
    }
    return (
        "You are a local command interpreter for a medical monitor application.\n"
        "Convert free-form voice text into canonical structured commands.\n"
        "Respond with JSON only. Do not include markdown or explanations.\n"
        "Do not invent commands outside this valid command list:\n"
        f"{json.dumps(_command_names(), ensure_ascii=True)}\n"
        "JSON schema to follow strictly:\n"
        f"{json.dumps(build_llm_json_schema(), ensure_ascii=True)}\n"
        "Domain rules:\n"
        "- 'monitor', 'screen', 'pantalla', and 'display' mean monitor.\n"
        "- monitor 1, pantalla uno, pantalla una, primera pantalla => SELECT_MONITOR monitor=1.\n"
        "- monitor 2, pantalla dos, segunda pantalla => SELECT_MONITOR monitor=2.\n"
        "- If the user says an exact size in inches, return SET_SIZE with size_inches.\n"
        "- redimensiona, ajusta, cambia tamano, escala, pon a X pulgadas => SET_SIZE.\n"
        "- If the user says grande/bigger/larger without a number => INCREASE_SIZE.\n"
        "- If the user says pequeno/chico/reduce/smaller without a number => DECREASE_SIZE.\n"
        "- izquierda/derecha/arriba/abajo/left/right/up/down map to MOVE_* commands.\n"
        "- aleja, alejar, alejalo, aleja lo, move away, zoom out mean ZOOM_OUT, not MOVE_LEFT, MOVE_RIGHT, MOVE_UP or MOVE_DOWN.\n"
        "- acerca, acercar, acercalo, bring closer, zoom in mean ZOOM_IN, not movement.\n"
        "- Distance units like 1 metro, 2 metros, 50 centimetros after aleja/acerca describe zoom distance or intensity. They must not create MOVE_* commands.\n"
        "- Only use MOVE_LEFT, MOVE_RIGHT, MOVE_UP or MOVE_DOWN when the user explicitly says izquierda, derecha, arriba, abajo, left, right, up or down.\n"
        "- For 'Redimensiona a 72 pulgadas el monitor 1', return SELECT_MONITOR monitor=1 and SET_SIZE size_inches=72.\n"
        "- If a command targets a monitor, return SELECT_MONITOR first. Do not attach monitor to SET_SIZE, MOVE_LEFT, MOVE_RIGHT, ZOOM_IN, ZOOM_OUT, INCREASE_SIZE or DECREASE_SIZE when SELECT_MONITOR can represent the target.\n"
        '- For input "Necesito que el monitor 2 este en 75 pulgadas", expected response is {"commands":[{"command":"SELECT_MONITOR","monitor":2},{"command":"SET_SIZE","size_inches":75}]}. Do not return {"command":"SET_SIZE","monitor":2,"size_inches":75}.\n'
        "- If previous_commands includes SELECT_MONITOR and SET_SIZE is missing, complete the list without unnecessary duplicates.\n"
        "- If uncertain, return UNKNOWN or set needs_confirmation=true.\n"
        "Input payload:\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
    )


def _parse_ollama_content(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Extract JSON content from an Ollama chat response."""

    if "commands" in payload:
        return payload

    content = None
    if isinstance(payload.get("message"), dict):
        content = payload["message"].get("content")
    elif "response" in payload:
        content = payload.get("response")

    if content is None:
        return None

    return _extract_json_object(content)


def _extract_json_object(content: Any) -> Optional[dict[str, Any]]:
    """Extract the first valid JSON object from LLM output."""

    if isinstance(content, dict):
        return content
    if not isinstance(content, str):
        return None

    try:
        parsed = json.loads(content)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        pass

    markdown_match = re.search(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        content,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if markdown_match:
        try:
            parsed = json.loads(markdown_match.group(1))
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            pass

    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", content):
        try:
            parsed, _ = decoder.raw_decode(content[match.start() :])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def _safe_command_name(value: Any) -> CommandName:
    try:
        return CommandName(value)
    except (TypeError, ValueError):
        return CommandName.UNKNOWN


def _safe_int_or_none(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.80
    return max(0.0, min(_confidence_cap(), confidence))


def parse_llm_response(
    data: dict[str, Any],
    *,
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str] = None,
) -> Optional[NormalizeResponse]:
    """Validate raw LLM JSON and return a safe NormalizeResponse."""

    commands_data = data.get("commands")
    if not isinstance(commands_data, list) or not commands_data:
        return None

    commands: list[NormalizedCommand] = []
    for item in commands_data:
        if not isinstance(item, dict):
            return None

        command_name = _safe_command_name(item.get("command"))
        confidence = _safe_confidence(item.get("confidence", 0.80))
        try:
            commands.append(
                NormalizedCommand(
                    command=command_name,
                    confidence=confidence,
                    method=MatchMethod.llm,
                    monitor=_safe_int_or_none(item.get("monitor")),
                    layout=_safe_int_or_none(item.get("layout")),
                    size_inches=_safe_int_or_none(item.get("size_inches")),
                    value=item.get("value"),
                    raw_fragment=item.get("raw_fragment") or normalized_text,
                )
            )
        except Exception:
            if command_name == CommandName.UNKNOWN:
                commands.append(
                    NormalizedCommand(
                        command=CommandName.UNKNOWN,
                        confidence=confidence,
                        method=MatchMethod.llm,
                        raw_fragment=item.get("raw_fragment") or normalized_text,
                    )
                )
                continue
            return None

    commands = canonicalize_commands(commands)
    accept_threshold = _accept_threshold()
    needs_confirmation = bool(data.get("needs_confirmation", False)) or any(
        command.confidence < accept_threshold for command in commands
    )
    return NormalizeResponse(
        ok=all(command.command != CommandName.UNKNOWN for command in commands),
        raw_text=raw_text,
        normalized_text=normalized_text,
        language=language_hint,
        commands=commands,
        needs_confirmation=needs_confirmation,
        message=data.get("message"),
    )


def interpret_commands_with_llm(
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str] = None,
    context: Optional[dict] = None,
    previous_commands: Optional[list[NormalizedCommand]] = None,
    completeness_reason: Optional[str] = None,
) -> Optional[NormalizeResponse]:
    """Call Ollama locally and interpret text as canonical commands."""

    prompt = build_llm_command_prompt(
        raw_text=raw_text,
        normalized_text=normalized_text,
        language_hint=language_hint,
        context=context,
        previous_commands=previous_commands,
        completeness_reason=completeness_reason,
    )
    request_payload = {
        "model": _runtime_str("OLLAMA_MODEL", config.OLLAMA_MODEL),
        "stream": False,
        "format": build_llm_json_schema(),
        "prompt": prompt,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
    }

    base_url = _runtime_str("OLLAMA_BASE_URL", config.OLLAMA_BASE_URL)
    url = f"{base_url.rstrip('/')}/api/chat"
    try:
        with httpx.Client(timeout=_ollama_timeout_seconds()) as client:
            payload = _post_ollama_with_optional_schema(client, url, request_payload)
    except Exception:
        return None

    parsed = _parse_ollama_content(payload)
    if parsed is None:
        return None

    return parse_llm_response(
        parsed,
        raw_text=raw_text,
        normalized_text=normalized_text,
        language_hint=language_hint,
    )


def _post_ollama_with_optional_schema(
    client: httpx.Client,
    url: str,
    request_payload: dict[str, Any],
) -> dict[str, Any]:
    """Post to Ollama with schema, then retry once without schema if rejected."""

    try:
        response = client.post(url, json=request_payload)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning(
            "Ollama structured output request failed; retrying without schema",
            extra={"event": "ollama_schema_retry"},
        )
        fallback_payload = dict(request_payload)
        fallback_payload.pop("format", None)
        response = client.post(url, json=fallback_payload)
        response.raise_for_status()
        return response.json()


def ollama_fallback_normalize(
    text: str,
    normalized_text: str,
    language_hint: Optional[str] = None,
) -> Optional[NormalizeResponse]:
    """Backward-compatible wrapper for the Ollama command interpreter."""

    return interpret_commands_with_llm(
        raw_text=text,
        normalized_text=normalized_text,
        language_hint=language_hint,
    )
