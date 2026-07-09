from __future__ import annotations

"""HTTP routes for the flexible v2 command API."""

from typing import Any

from fastapi import APIRouter, HTTPException

from app.normalizer import normalize_command_text
from app.services.command_spec_service import (
    CommandSpec,
    get_active_command_specs,
    get_command_spec_by_code,
)
from app.v2.adapter import v1_response_to_v2
from app.v2.dynamic_command_validation import validate_dynamic_command
from app.v2.llm_interpreter import build_v2_llm_prompt
from app.v2.normalizer import normalize_command_text_v2
from app.v2.schemas import CommandSpecResponse, NormalizeV2Request, NormalizeV2Response


router = APIRouter(prefix="/v2/commands", tags=["commands-v2"])


def _spec_to_response(spec: CommandSpec, *, include_examples: bool = True) -> CommandSpecResponse:
    return CommandSpecResponse(
        code=spec.code,
        type=spec.command_type,
        client_action_key=spec.client_action_key,
        display_name=spec.display_name,
        description=spec.description,
        category=spec.category,
        parameters=[
            parameter.model_dump(mode="json") for parameter in spec.parameters
        ],
        examples=list(spec.examples) if include_examples else None,
    )


@router.post("/normalize", response_model=NormalizeV2Response)
def normalize_commands_v2(payload: NormalizeV2Request) -> NormalizeV2Response:
    """Normalize text into core and custom command results."""

    return normalize_command_text_v2(
        text=payload.text,
        language_hint=payload.language_hint,
        context=payload.context,
        client_capabilities=payload.client_capabilities,
    )


@router.get("/specs", response_model=list[CommandSpecResponse])
def read_command_specs_v2() -> list[CommandSpecResponse]:
    """Return active core/custom command specs for client synchronization."""

    return [_spec_to_response(spec) for spec in get_active_command_specs()]


@router.get("/specs/{code}", response_model=CommandSpecResponse)
def read_command_spec_v2(code: str) -> CommandSpecResponse:
    """Return one active command spec by code."""

    spec = get_command_spec_by_code(code)
    if spec is None:
        raise HTTPException(status_code=404, detail="Command spec not found.")
    return _spec_to_response(spec)


@router.post("/debug")
def debug_commands_v2(payload: NormalizeV2Request) -> dict[str, Any]:
    """Return v2 debug data without changing the public v1 debug payload."""

    v1_response = normalize_command_text(
        text=payload.text,
        language_hint=payload.language_hint,
        context=payload.context,
    )
    v2_response = normalize_command_text_v2(
        text=payload.text,
        language_hint=payload.language_hint,
        context=payload.context,
        client_capabilities=payload.client_capabilities,
    )
    specs = get_active_command_specs()
    spec_payload = [_spec_to_response(spec).model_dump(mode="json") for spec in specs]

    validation_results = []
    for command in v2_response.commands:
        try:
            validate_dynamic_command(
                command,
                specs,
                client_capabilities=payload.client_capabilities,
            )
            validation_results.append(
                {
                    "code": command.code,
                    "valid": True,
                    "client_action_key": command.client_action_key,
                }
            )
        except ValueError as exc:
            validation_results.append(
                {
                    "code": command.code,
                    "valid": False,
                    "error": str(exc),
                    "client_action_key": command.client_action_key,
                }
            )

    prompt_summary = {
        "spec_count": len(specs),
        "custom_command_count": sum(1 for spec in specs if spec.command_type == "custom"),
        "client_capabilities": payload.client_capabilities or [],
        "prompt_available": bool(specs),
    }
    prompt_preview = None
    if specs:
        prompt_preview = build_v2_llm_prompt(
            raw_text=payload.text,
            normalized_text=v1_response.normalized_text,
            language_hint=payload.language_hint,
            context=payload.context,
            previous_commands=v1_response_to_v2(v1_response).commands,
            specs=specs,
        )[:500]

    return {
        "raw_text": payload.text,
        "v1_response": v1_response.model_dump(mode="json"),
        "v2_response": v2_response.model_dump(mode="json"),
        "command_specs_used": spec_payload,
        "llm_prompt_summary": prompt_summary,
        "llm_prompt_preview": prompt_preview,
        "dynamic_validation": validation_results,
        "client_capabilities_filtering": {
            "enabled": payload.client_capabilities is not None,
            "client_capabilities": payload.client_capabilities or [],
        },
    }
