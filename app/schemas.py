from __future__ import annotations

"""Pydantic schemas for the command normalization API.

These models define the public contract for the normalization service.
"""

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


ALLOWED_MONITORS = {1, 2}
ALLOWED_LAYOUTS = {1, 2}


class CommandName(str, Enum):
    """Canonical command names returned by the API."""

    SELECT_MONITOR = "SELECT_MONITOR"
    MOVE_LEFT = "MOVE_LEFT"
    MOVE_RIGHT = "MOVE_RIGHT"
    MOVE_UP = "MOVE_UP"
    MOVE_DOWN = "MOVE_DOWN"
    ZOOM_IN = "ZOOM_IN"
    ZOOM_OUT = "ZOOM_OUT"
    INCREASE_SIZE = "INCREASE_SIZE"
    DECREASE_SIZE = "DECREASE_SIZE"
    SET_SIZE = "SET_SIZE"
    FOLLOW_ME = "FOLLOW_ME"
    STOP_FOLLOW_ME = "STOP_FOLLOW_ME"
    RECENTER_OBJECTS = "RECENTER_OBJECTS"
    RESET_POSITION = "RESET_POSITION"
    SET_LAYOUT = "SET_LAYOUT"
    SHOW_AITROL = "SHOW_AITROL"
    CLOSE_AITROL = "CLOSE_AITROL"
    SHOW_VOICE_COMMANDS = "SHOW_VOICE_COMMANDS"
    CLOSE_VOICE_COMMANDS = "CLOSE_VOICE_COMMANDS"
    OPEN_SETTINGS = "OPEN_SETTINGS"
    CAPTURE = "CAPTURE"
    START_STREAM = "START_STREAM"
    START_RECORDING = "START_RECORDING"
    STOP_STREAM = "STOP_STREAM"
    STOP_ACTIVE = "STOP_ACTIVE"
    UNKNOWN = "UNKNOWN"


class MatchMethod(str, Enum):
    """How the command was resolved."""

    exact_rule = "exact_rule"
    entity_rule = "entity_rule"
    fuzzy = "fuzzy"
    semantic = "semantic"
    llm = "llm"
    unknown = "unknown"


class NormalizeRequest(BaseModel):
    """Input payload for command normalization.

    Example:
        NormalizeRequest(text="put monitor two on the left", language_hint="en")
    """

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "text": "put monitor two on the left",
                "language_hint": "en",
                "context": {"selected_monitor": None, "active_action": "stream"},
            }
        }
    )

    text: str = Field(..., description="Raw transcribed voice command.")
    language_hint: Optional[str] = Field(
        default=None,
        description="Optional language hint such as 'en' or 'es'.",
    )
    context: Optional[dict[str, Any]] = Field(
        default=None,
        description="Optional execution context from the caller.",
    )


class NormalizedCommand(BaseModel):
    """Single canonical command extracted from the input text."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "command": "SELECT_MONITOR",
                "confidence": 0.97,
                "method": "entity_rule",
                "monitor": 2,
                "raw_fragment": "monitor two",
            }
        }
    )

    command: CommandName
    confidence: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Confidence score between 0 and 1.",
    )
    method: MatchMethod
    monitor: Optional[int] = Field(default=None, description="Monitor identifier.")
    layout: Optional[int] = Field(default=None, description="Layout identifier.")
    size_inches: Optional[int] = Field(
        default=None, description="Target size in inches."
    )
    value: Optional[str] = Field(default=None, description="Optional free-form value.")
    raw_fragment: Optional[str] = Field(
        default=None,
        description="Original text fragment associated with the command.",
    )

    @model_validator(mode="after")
    def validate_command_specific_fields(self) -> "NormalizedCommand":
        """Enforce entity constraints for command-specific payloads."""

        if self.command == CommandName.SET_SIZE:
            if self.size_inches is None or self.size_inches <= 0:
                raise ValueError("SET_SIZE requires a positive size_inches value.")
            from app.services.size_validation_service import is_valid_size_inches

            if not is_valid_size_inches(self.size_inches):
                raise ValueError(
                    "SET_SIZE size_inches is outside the configured allowed range."
                )

        if self.command == CommandName.SELECT_MONITOR:
            if self.monitor not in ALLOWED_MONITORS:
                raise ValueError(
                    f"SELECT_MONITOR requires monitor in {sorted(ALLOWED_MONITORS)}."
                )

        if self.command == CommandName.SET_LAYOUT:
            if self.layout not in ALLOWED_LAYOUTS:
                raise ValueError(
                    f"SET_LAYOUT requires layout in {sorted(ALLOWED_LAYOUTS)}."
                )

        return self


class NormalizeResponse(BaseModel):
    """Normalized response returned by the API."""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "ok": True,
                "raw_text": "make monitor one bigger",
                "normalized_text": "make monitor one bigger",
                "language": "en",
                "commands": [
                    {
                        "command": "SELECT_MONITOR",
                        "confidence": 0.96,
                        "method": "entity_rule",
                        "monitor": 1,
                        "raw_fragment": "monitor one",
                    },
                    {
                        "command": "INCREASE_SIZE",
                        "confidence": 0.88,
                        "method": "semantic",
                        "raw_fragment": "bigger",
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
    commands: list[NormalizedCommand]
    needs_confirmation: bool
    message: Optional[str] = None
