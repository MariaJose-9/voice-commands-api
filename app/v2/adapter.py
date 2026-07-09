from __future__ import annotations

"""Adapters from the stable v1 response shape to flexible v2 schemas."""

from app.schemas import NormalizedCommand, NormalizeResponse
from app.v2.schemas import DynamicCommand, NormalizeV2Response


def _snake_case_code(code: str) -> str:
    return code.strip().lower()


def v1_command_to_v2(command: NormalizedCommand) -> DynamicCommand:
    """Convert a v1 enum-backed command into a flexible v2 command."""

    code = command.command.value
    params = {}
    if command.monitor is not None:
        params["monitor"] = command.monitor
    if command.layout is not None:
        params["layout"] = command.layout
    if command.size_inches is not None:
        params["size_inches"] = command.size_inches
    if command.value is not None:
        params["value"] = command.value

    return DynamicCommand(
        code=code,
        type="core",
        client_action_key=_snake_case_code(code),
        confidence=command.confidence,
        method=command.method.value,
        params=params,
        raw_fragment=command.raw_fragment,
        needs_confirmation=None,
    )


def v1_response_to_v2(response: NormalizeResponse) -> NormalizeV2Response:
    """Convert a full v1 normalization response into the v2 response shape."""

    return NormalizeV2Response(
        ok=response.ok,
        raw_text=response.raw_text,
        normalized_text=response.normalized_text,
        language=response.language,
        commands=[v1_command_to_v2(command) for command in response.commands],
        needs_confirmation=response.needs_confirmation,
        message=response.message,
    )
