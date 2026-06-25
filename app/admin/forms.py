"""Admin form models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from fastapi import Form


class LoginForm(BaseModel):
    """Simple login form for the admin panel."""

    model_config = ConfigDict(extra="forbid")

    email: str = Field(default="")
    password: str = Field(default="")

    @classmethod
    def as_form(
        cls,
        email: str = Form(...),
        password: str = Form(...),
    ) -> "LoginForm":
        return cls(email=email, password=password)


class CommandUpdateForm(BaseModel):
    """Editable fields for a command definition."""

    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(default="")
    description: str = Field(default="")
    category: str = Field(default="")
    enabled: bool = Field(default=True)
    priority: int = Field(default=50)
    min_confidence: float = Field(default=0.72)

    @classmethod
    def as_form(
        cls,
        display_name: str = Form(...),
        description: str = Form(""),
        category: str = Form(""),
        enabled: bool = Form(False),
        priority: int = Form(...),
        min_confidence: float = Form(...),
    ) -> "CommandUpdateForm":
        return cls(
            display_name=display_name,
            description=description,
            category=category,
            enabled=enabled,
            priority=priority,
            min_confidence=min_confidence,
        )


class ExampleCreateForm(BaseModel):
    """Form payload for creating a command example."""

    model_config = ConfigDict(extra="forbid")

    phrase: str = Field(default="")
    language: str = Field(default="")
    match_type: str = Field(default="semantic")
    enabled: bool = Field(default=True)

    @classmethod
    def as_form(
        cls,
        phrase: str = Form(...),
        language: str = Form(""),
        match_type: str = Form("semantic"),
        enabled: bool = Form(False),
    ) -> "ExampleCreateForm":
        return cls(
            phrase=phrase,
            language=language,
            match_type=match_type,
            enabled=enabled,
        )


class ExampleUpdateForm(BaseModel):
    """Form payload for updating an existing command example."""

    model_config = ConfigDict(extra="forbid")

    phrase: str = Field(default="")
    language: str = Field(default="")
    match_type: str = Field(default="semantic")
    enabled: bool = Field(default=True)

    @classmethod
    def as_form(
        cls,
        phrase: str = Form(...),
        language: str = Form(""),
        match_type: str = Form("semantic"),
        enabled: bool = Form(False),
    ) -> "ExampleUpdateForm":
        return cls(
            phrase=phrase,
            language=language,
            match_type=match_type,
            enabled=enabled,
        )


class EntityValueCreateForm(BaseModel):
    """Form payload for creating an entity value."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(default="")
    label: str = Field(default="")
    enabled: bool = Field(default=True)

    @classmethod
    def as_form(
        cls,
        value: str = Form(...),
        label: str = Form(""),
        enabled: bool = Form(False),
    ) -> "EntityValueCreateForm":
        return cls(value=value, label=label, enabled=enabled)


class EntityValueUpdateForm(BaseModel):
    """Form payload for updating an entity value."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(default="")
    label: str = Field(default="")
    enabled: bool = Field(default=True)

    @classmethod
    def as_form(
        cls,
        value: str = Form(...),
        label: str = Form(""),
        enabled: bool = Form(False),
    ) -> "EntityValueUpdateForm":
        return cls(value=value, label=label, enabled=enabled)


class EntityAliasCreateForm(BaseModel):
    """Form payload for creating an entity alias."""

    model_config = ConfigDict(extra="forbid")

    phrase: str = Field(default="")
    language: str = Field(default="")
    enabled: bool = Field(default=True)

    @classmethod
    def as_form(
        cls,
        phrase: str = Form(...),
        language: str = Form(""),
        enabled: bool = Form(False),
    ) -> "EntityAliasCreateForm":
        return cls(phrase=phrase, language=language, enabled=enabled)


class EntityAliasUpdateForm(BaseModel):
    """Form payload for updating an entity alias."""

    model_config = ConfigDict(extra="forbid")

    phrase: str = Field(default="")
    language: str = Field(default="")
    enabled: bool = Field(default=True)

    @classmethod
    def as_form(
        cls,
        phrase: str = Form(...),
        language: str = Form(""),
        enabled: bool = Form(False),
    ) -> "EntityAliasUpdateForm":
        return cls(phrase=phrase, language=language, enabled=enabled)
