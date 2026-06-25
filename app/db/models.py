"""SQLModel models for command administration."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional

from sqlalchemy import JSON, Column, DateTime, Enum as SAEnum, String, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.schemas import CommandName


def utc_now() -> datetime:
    """Return the current UTC timestamp."""

    return datetime.now(timezone.utc)


class UserRole(str, Enum):
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class MatchType(str, Enum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    SEMANTIC = "semantic"


class ExampleSource(str, Enum):
    SEED = "seed"
    ADMIN = "admin"
    REVIEW = "review"


class ReviewStatus(str, Enum):
    PENDING = "pending"
    CONVERTED_TO_EXAMPLE = "converted_to_example"
    IGNORED = "ignored"


class CatalogStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class SettingValueType(str, Enum):
    STR = "str"


def _enum_column(enum_cls: type[Enum], name: str) -> SAEnum:
    """Persist enum values instead of enum member names."""

    return SAEnum(
        enum_cls,
        name=name,
        values_callable=lambda members: [member.value for member in members],
    )


class AdminUser(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    email: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    password_hash: str = Field(sa_column=Column(String(255), nullable=False))
    role: UserRole = Field(
        default=UserRole.ADMIN,
        sa_column=Column(_enum_column(UserRole, "userrole"), nullable=False),
    )
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CommandDefinition(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: CommandName = Field(index=True, unique=True)
    display_name: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(String(1024), nullable=True),
    )
    category: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    enabled: bool = Field(default=True)
    priority: int = Field(default=50)
    min_confidence: float = Field(default=0.72)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CommandExample(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    command_id: int = Field(foreign_key="commanddefinition.id")
    phrase: str = Field(sa_column=Column(String(500), nullable=False))
    normalized_phrase: str = Field(
        sa_column=Column(String(500), index=True, nullable=False)
    )
    language: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    match_type: MatchType = Field(
        default=MatchType.SEMANTIC,
        sa_column=Column(_enum_column(MatchType, "matchtype"), nullable=False),
    )
    enabled: bool = Field(default=True)
    source: ExampleSource = Field(
        default=ExampleSource.ADMIN,
        sa_column=Column(_enum_column(ExampleSource, "examplesource"), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class EntityType(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    code: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    display_name: str = Field(sa_column=Column(String(255), nullable=False))
    description: Optional[str] = Field(
        default=None,
        sa_column=Column(String(1024), nullable=True),
    )
    enabled: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class EntityValue(SQLModel, table=True):
    __table_args__ = (UniqueConstraint("entity_type_id", "value"),)

    id: Optional[int] = Field(default=None, primary_key=True)
    entity_type_id: int = Field(foreign_key="entitytype.id")
    value: str = Field(sa_column=Column(String(255), nullable=False))
    label: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    enabled: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class EntityValueAlias(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    entity_value_id: int = Field(foreign_key="entityvalue.id")
    phrase: str = Field(sa_column=Column(String(500), nullable=False))
    normalized_phrase: str = Field(
        sa_column=Column(String(500), index=True, nullable=False)
    )
    language: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    enabled: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class NormalizationLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    raw_text: str = Field(sa_column=Column(String(500), nullable=False))
    normalized_text: Optional[str] = Field(
        default=None,
        sa_column=Column(String(500), nullable=True),
    )
    language: Optional[str] = Field(
        default=None,
        sa_column=Column(String(32), nullable=True),
    )
    result_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    top_confidence: Optional[float] = Field(default=None)
    needs_confirmation: bool = Field(default=False)
    review_status: ReviewStatus = Field(
        default=ReviewStatus.PENDING,
        sa_column=Column(_enum_column(ReviewStatus, "reviewstatus"), nullable=False),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class CatalogVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    version_number: int = Field(index=True, unique=True)
    status: CatalogStatus = Field(
        default=CatalogStatus.DRAFT,
        sa_column=Column(_enum_column(CatalogStatus, "catalogstatus"), nullable=False),
    )
    snapshot_json: dict = Field(sa_column=Column(JSON, nullable=False))
    created_by: Optional[int] = Field(default=None, foreign_key="adminuser.id")
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    published_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class AppSetting(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    key: str = Field(
        sa_column=Column(String(255), unique=True, index=True, nullable=False)
    )
    value: str = Field(sa_column=Column(String(1024), nullable=False))
    value_type: SettingValueType = Field(
        default=SettingValueType.STR,
        sa_column=Column(_enum_column(SettingValueType, "settingvaluetype"), nullable=False),
    )
    updated_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    actor_user_id: Optional[int] = Field(default=None, foreign_key="adminuser.id")
    action: str = Field(sa_column=Column(String(255), nullable=False))
    entity_type: Optional[str] = Field(
        default=None,
        sa_column=Column(String(255), nullable=True),
    )
    entity_id: Optional[int] = Field(default=None)
    payload_json: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
