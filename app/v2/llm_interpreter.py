from __future__ import annotations

"""Ollama-backed interpreter for flexible v2 core/custom commands."""

import json
import logging
from typing import Any, Optional

import httpx

from app import config
from app.ollama_fallback import (
    _extract_json_object,
    _ollama_timeout_seconds,
    _parse_ollama_content,
    _post_ollama_with_optional_schema,
    _runtime_str,
)
from app.services.command_spec_service import CommandSpec, get_active_command_specs
from app.v2.dynamic_command_validation import validate_dynamic_command
from app.v2.schemas import DynamicCommand


logger = logging.getLogger(__name__)


def _safe_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        confidence = 0.80
    return max(0.0, min(1.0, confidence))


def build_v2_llm_json_schema(specs: list[CommandSpec]) -> dict[str, Any]:
    """Return JSON schema for flexible v2 LLM command output."""

    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["commands", "needs_confirmation"],
        "properties": {
            "needs_confirmation": {"type": "boolean"},
            "commands": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["code", "params", "confidence", "raw_fragment"],
                    "properties": {
                        "code": {
                            "type": "string",
                            "enum": [spec.code for spec in specs],
                        },
                        "params": {"type": "object"},
                        "confidence": {"type": ["number", "null"]},
                        "raw_fragment": {"type": ["string", "null"]},
                    },
                },
            },
        },
    }


def _parameter_for_prompt(parameter) -> dict[str, Any]:
    return {
        "slot_name": parameter.slot_name,
        "entity_code": parameter.entity_code,
        "target_field": parameter.target_field,
        "required": parameter.required,
        "allow_multiple": parameter.allow_multiple,
        "data_type": parameter.data_type,
        "unit": parameter.unit,
        "dynamic_values": parameter.dynamic_values,
        "min_value": parameter.min_value,
        "max_value": parameter.max_value,
        "description": parameter.description,
        "extraction_hint": parameter.extraction_hint,
    }


def _spec_for_prompt(spec: CommandSpec) -> dict[str, Any]:
    return {
        "code": spec.code,
        "type": spec.command_type,
        "client_action_key": spec.client_action_key,
        "display_name": spec.display_name,
        "description": spec.description,
        "category": spec.category,
        "examples": spec.examples[:8],
        "parameters": [_parameter_for_prompt(parameter) for parameter in spec.parameters],
    }


def build_v2_llm_prompt(
    *,
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str],
    context: Optional[dict],
    previous_commands: list[DynamicCommand],
    specs: list[CommandSpec],
) -> str:
    """Build a prompt that allows the LLM to return active core/custom commands."""

    payload = {
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "language_hint": language_hint,
        "context": context or {},
        "previous_commands": [command.model_dump(mode="json") for command in previous_commands],
    }
    return (
        "You are a command interpreter for a medical monitor application.\n"
        "Return JSON only. Do not include markdown or explanations.\n"
        "Use only command codes from the active command specs below. Core and custom commands are both allowed.\n"
        "For each command return: code, params, confidence, raw_fragment.\n"
        "Fill params using each command parameter target_field. Required parameters must be present.\n"
        "Do not invent command codes. If no active command applies, return an empty commands list and needs_confirmation=true.\n"
        "Active command specs:\n"
        f"{json.dumps([_spec_for_prompt(spec) for spec in specs], ensure_ascii=False)}\n"
        "Expected JSON schema:\n"
        f"{json.dumps(build_v2_llm_json_schema(specs), ensure_ascii=True)}\n"
        "Input payload:\n"
        f"{json.dumps(payload, ensure_ascii=False)}\n"
    )


def parse_v2_llm_response(
    data: dict[str, Any],
    *,
    specs: list[CommandSpec],
    client_capabilities: Optional[list[str]] = None,
) -> tuple[list[DynamicCommand], bool]:
    """Parse and validate v2 LLM output into DynamicCommand objects."""

    commands_data = data.get("commands")
    if not isinstance(commands_data, list):
        return [], True

    spec_by_code = {spec.code: spec for spec in specs}
    needs_confirmation = bool(data.get("needs_confirmation", False))
    commands: list[DynamicCommand] = []

    for item in commands_data:
        if not isinstance(item, dict):
            needs_confirmation = True
            continue
        code = str(item.get("code") or "")
        spec = spec_by_code.get(code)
        if spec is None:
            needs_confirmation = True
            continue
        try:
            command = DynamicCommand(
                code=code,
                type=spec.command_type,
                client_action_key=spec.client_action_key,
                confidence=_safe_confidence(item.get("confidence")),
                method="llm",
                params=item.get("params") if isinstance(item.get("params"), dict) else {},
                raw_fragment=item.get("raw_fragment"),
                needs_confirmation=None,
            )
            command = validate_dynamic_command(
                command,
                specs,
                client_capabilities=client_capabilities,
            )
        except Exception:
            needs_confirmation = True
            continue
        commands.append(command)

    return commands, needs_confirmation


def interpret_dynamic_commands_with_llm(
    *,
    raw_text: str,
    normalized_text: str,
    language_hint: Optional[str] = None,
    context: Optional[dict] = None,
    previous_commands: Optional[list[DynamicCommand]] = None,
    specs: Optional[list[CommandSpec]] = None,
    client_capabilities: Optional[list[str]] = None,
) -> tuple[list[DynamicCommand], bool]:
    """Call Ollama and return validated flexible v2 commands."""

    active_specs = specs or get_active_command_specs()
    if not active_specs:
        return [], True

    prompt = build_v2_llm_prompt(
        raw_text=raw_text,
        normalized_text=normalized_text,
        language_hint=language_hint,
        context=context,
        previous_commands=previous_commands or [],
        specs=active_specs,
    )
    request_payload = {
        "model": _runtime_str("OLLAMA_MODEL", config.OLLAMA_MODEL),
        "stream": False,
        "format": build_v2_llm_json_schema(active_specs),
        "prompt": prompt,
        "messages": [{"role": "user", "content": prompt}],
    }
    base_url = _runtime_str("OLLAMA_BASE_URL", config.OLLAMA_BASE_URL)
    url = f"{base_url.rstrip('/')}/api/chat"
    try:
        with httpx.Client(timeout=_ollama_timeout_seconds()) as client:
            payload = _post_ollama_with_optional_schema(client, url, request_payload)
    except Exception:
        logger.exception(
            "v2 LLM dynamic command interpretation failed",
            extra={"event": "v2_llm_interpret_failed"},
        )
        return [], True

    parsed = _parse_ollama_content(payload)
    if parsed is None:
        parsed = _extract_json_object(payload)
    if parsed is None:
        return [], True

    return parse_v2_llm_response(
        parsed,
        specs=active_specs,
        client_capabilities=client_capabilities,
    )
