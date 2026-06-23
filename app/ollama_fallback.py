"""Optional local LLM fallback using Ollama."""

from __future__ import annotations

import json
from typing import Any, Optional

import httpx

from app.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from app.schemas import CommandName, MatchMethod, NormalizeResponse, NormalizedCommand


_OLLAMA_TIMEOUT_SECONDS = 3.0


def _command_names() -> list[str]:
    """Return the list of valid canonical command names."""

    return [command.value for command in CommandName if command != CommandName.UNKNOWN]


def _response_schema() -> dict[str, Any]:
    """Return the constrained JSON shape expected from Ollama."""

    return {
        "type": "object",
        "required": [
            "ok",
            "raw_text",
            "normalized_text",
            "language",
            "commands",
            "needs_confirmation",
            "message",
        ],
        "properties": {
            "ok": {"type": "boolean"},
            "raw_text": {"type": "string"},
            "normalized_text": {"type": "string"},
            "language": {"type": ["string", "null"]},
            "needs_confirmation": {"type": "boolean"},
            "message": {"type": ["string", "null"]},
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["command"],
                    "properties": {
                        "command": {"type": "string", "enum": _command_names()},
                        "monitor": {"type": ["integer", "null"]},
                        "layout": {"type": ["integer", "null"]},
                        "size_inches": {"type": ["integer", "null"]},
                        "value": {"type": ["string", "null"]},
                        "raw_fragment": {"type": ["string", "null"]},
                    },
                },
            },
        },
    }


def _prompt(text: str, normalized_text: str, language_hint: Optional[str]) -> str:
    """Build a strict prompt for local JSON-only command extraction."""

    return (
        "You are a local command normalizer.\n"
        "Valid commands:\n"
        f"{json.dumps(_command_names())}\n"
        "Return only valid JSON matching this schema:\n"
        f"{json.dumps(_response_schema())}\n"
        "Rules:\n"
        "- Respond with JSON only.\n"
        "- Do not include markdown.\n"
        "- Use only the valid commands list.\n"
        "- If uncertain, use command UNKNOWN.\n"
        "- Keep confidence implicit; the caller will set llm confidence.\n"
        f"language_hint={language_hint!r}\n"
        f"raw_text={text!r}\n"
        f"normalized_text={normalized_text!r}\n"
    )


def _parse_ollama_content(payload: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Extract JSON content from an Ollama chat response."""

    try:
        content = payload["message"]["content"]
    except (KeyError, TypeError):
        return None

    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError):
        return None


def _normalize_llm_response(
    data: dict[str, Any],
    *,
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str],
) -> Optional[NormalizeResponse]:
    """Convert Ollama JSON into a safe NormalizeResponse."""

    commands_data = data.get("commands")
    if not isinstance(commands_data, list) or not commands_data:
        return None

    commands: list[NormalizedCommand] = []
    for item in commands_data:
        try:
            command_name = CommandName(item["command"])
        except (KeyError, ValueError, TypeError):
            return None

        try:
            commands.append(
                NormalizedCommand(
                    command=command_name,
                    confidence=min(0.70, float(item.get("confidence", 0.70))),
                    method=MatchMethod.llm,
                    monitor=item.get("monitor"),
                    layout=item.get("layout"),
                    size_inches=item.get("size_inches"),
                    value=item.get("value"),
                    raw_fragment=item.get("raw_fragment") or normalized_text,
                )
            )
        except Exception:
            return None

    return NormalizeResponse(
        ok=all(command.command != CommandName.UNKNOWN for command in commands),
        raw_text=raw_text,
        normalized_text=normalized_text,
        language=language_hint,
        commands=commands,
        needs_confirmation=True,
        message=data.get("message"),
    )


def ollama_fallback_normalize(
    text: str,
    normalized_text: str,
    language_hint: Optional[str] = None,
) -> Optional[NormalizeResponse]:
    """Call Ollama locally and return a safe parsed response or None."""

    request_payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "format": _response_schema(),
        "messages": [
            {
                "role": "user",
                "content": _prompt(text, normalized_text, language_hint),
            }
        ],
    }

    try:
        with httpx.Client(timeout=_OLLAMA_TIMEOUT_SECONDS) as client:
            response = client.post(
                f"{OLLAMA_BASE_URL.rstrip('/')}/api/chat",
                json=request_payload,
            )
            response.raise_for_status()
            payload = response.json()
    except Exception:
        return None

    parsed = _parse_ollama_content(payload)
    if parsed is None:
        return None

    return _normalize_llm_response(
        parsed,
        raw_text=text,
        normalized_text=normalized_text,
        language_hint=language_hint,
    )
