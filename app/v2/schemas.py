from __future__ import annotations

"""Pydantic schemas for the flexible v2 command API."""

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class DynamicCommand(BaseModel):
    """Command result that supports core and admin-created command codes."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "ROTATE_SCREEN",
                "type": "custom",
                "client_action_key": "rotate_screen",
                "confidence": 0.91,
                "method": "llm",
                "params": {"monitor": 2, "angle": 90},
                "raw_fragment": "rota el monitor dos noventa grados",
                "needs_confirmation": False,
            }
        }
    )

    code: str = Field(..., description="Command code. Not restricted to the v1 enum.")
    type: Literal["core", "custom"]
    client_action_key: Optional[str] = Field(
        default=None,
        description="Client-side action key configured for the command.",
    )
    confidence: float = Field(..., ge=0.0, le=1.0)
    method: str
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Flexible command parameters, e.g. monitor, size_inches, angle.",
    )
    raw_fragment: Optional[str] = None
    needs_confirmation: Optional[bool] = None


class NormalizeV2Request(BaseModel):
    """Input payload for flexible command normalization."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "rota el monitor dos a noventa grados",
                "language_hint": "es",
                "context": {"selected_monitor": None},
                "client_capabilities": ["rotate_screen", "set_size"],
            }
        }
    )

    text: str
    language_hint: Optional[str] = None
    context: Optional[dict[str, Any]] = None
    client_capabilities: Optional[list[str]] = None


class NormalizeV2Response(BaseModel):
    """Flexible normalization response for core and custom commands."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "raw_text": "monitor dos a 75 pulgadas",
                "normalized_text": "monitor dos a 75 pulgadas",
                "language": "es",
                "commands": [
                    {
                        "code": "SELECT_MONITOR",
                        "type": "core",
                        "client_action_key": "select_monitor",
                        "confidence": 1.0,
                        "method": "entity_rule",
                        "params": {"monitor": 2},
                        "raw_fragment": "monitor dos",
                    },
                    {
                        "code": "SET_SIZE",
                        "type": "core",
                        "client_action_key": "set_size",
                        "confidence": 1.0,
                        "method": "entity_rule",
                        "params": {"size_inches": 75},
                        "raw_fragment": "75 pulgadas",
                    },
                ],
                "needs_confirmation": False,
                "message": None,
            }
        }
    )

    ok: bool
    raw_text: str
    normalized_text: str
    language: Optional[str] = None
    commands: list[DynamicCommand]
    needs_confirmation: bool
    message: Optional[str] = None


class CommandSpecResponse(BaseModel):
    """Public command specification shape for v2 clients."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "code": "ROTATE_SCREEN",
                "type": "custom",
                "client_action_key": "rotate_screen",
                "display_name": "Rotate Screen",
                "description": "Rotate selected screen.",
                "category": "Custom",
                "parameters": [
                    {
                        "slot_name": "angle",
                        "entity_code": "angle_degrees",
                        "target_field": "angle",
                        "required": True,
                    }
                ],
                "examples": ["rota el monitor dos noventa grados"],
            }
        }
    )

    code: str
    type: Literal["core", "custom"]
    client_action_key: Optional[str] = None
    display_name: str
    description: Optional[str] = None
    category: Optional[str] = None
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    examples: Optional[list[str]] = None
