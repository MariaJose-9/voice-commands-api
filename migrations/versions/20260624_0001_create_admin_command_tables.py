"""create admin command tables

Revision ID: 20260624_0001
Revises: 
Create Date: 2026-06-24 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260624_0001"
down_revision = None
branch_labels = None
depends_on = None


user_role_enum = sa.Enum("admin", "editor", "viewer", name="userrole")
command_name_enum = sa.Enum(
    "SELECT_MONITOR",
    "MOVE_LEFT",
    "MOVE_RIGHT",
    "MOVE_UP",
    "MOVE_DOWN",
    "ZOOM_IN",
    "ZOOM_OUT",
    "INCREASE_SIZE",
    "DECREASE_SIZE",
    "SET_SIZE",
    "FOLLOW_ME",
    "STOP_FOLLOW_ME",
    "RECENTER_OBJECTS",
    "RESET_POSITION",
    "SET_LAYOUT",
    "SHOW_AITROL",
    "CLOSE_AITROL",
    "SHOW_VOICE_COMMANDS",
    "CLOSE_VOICE_COMMANDS",
    "OPEN_SETTINGS",
    "CAPTURE",
    "START_STREAM",
    "START_RECORDING",
    "STOP_STREAM",
    "STOP_ACTIVE",
    "UNKNOWN",
    name="commandname",
)
match_type_enum = sa.Enum("exact", "fuzzy", "semantic", name="matchtype")
example_source_enum = sa.Enum("seed", "admin", "review", name="examplesource")
review_status_enum = sa.Enum(
    "pending",
    "converted_to_example",
    "ignored",
    name="reviewstatus",
)
catalog_status_enum = sa.Enum("draft", "active", "archived", name="catalogstatus")
setting_value_type_enum = sa.Enum("str", name="settingvaluetype")


def upgrade() -> None:
    op.create_table(
        "adminuser",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("role", user_role_enum, nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_adminuser_email"), "adminuser", ["email"], unique=True)

    op.create_table(
        "commanddefinition",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", command_name_enum, nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False),
        sa.Column("min_confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        op.f("ix_commanddefinition_code"),
        "commanddefinition",
        ["code"],
        unique=True,
    )

    op.create_table(
        "entitytype",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("code", sa.String(length=255), nullable=False),
        sa.Column("display_name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_entitytype_code"), "entitytype", ["code"], unique=True)

    op.create_table(
        "normalizationlog",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("raw_text", sa.String(length=500), nullable=False),
        sa.Column("normalized_text", sa.String(length=500), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("top_confidence", sa.Float(), nullable=True),
        sa.Column("needs_confirmation", sa.Boolean(), nullable=False),
        sa.Column("review_status", review_status_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "catalogversion",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("status", catalog_status_enum, nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["adminuser.id"]),
    )
    op.create_index(
        op.f("ix_catalogversion_version_number"),
        "catalogversion",
        ["version_number"],
        unique=True,
    )

    op.create_table(
        "appsetting",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.String(length=1024), nullable=False),
        sa.Column("value_type", setting_value_type_enum, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(op.f("ix_appsetting_key"), "appsetting", ["key"], unique=True)

    op.create_table(
        "auditlog",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("actor_user_id", sa.Integer(), nullable=True),
        sa.Column("action", sa.String(length=255), nullable=False),
        sa.Column("entity_type", sa.String(length=255), nullable=True),
        sa.Column("entity_id", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["actor_user_id"], ["adminuser.id"]),
    )

    op.create_table(
        "commandexample",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("command_id", sa.Integer(), nullable=False),
        sa.Column("phrase", sa.String(length=500), nullable=False),
        sa.Column("normalized_phrase", sa.String(length=500), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("match_type", match_type_enum, nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("source", example_source_enum, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["command_id"], ["commanddefinition.id"]),
    )
    op.create_index(
        op.f("ix_commandexample_normalized_phrase"),
        "commandexample",
        ["normalized_phrase"],
        unique=False,
    )

    op.create_table(
        "entityvalue",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("entity_type_id", sa.Integer(), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=False),
        sa.Column("label", sa.String(length=255), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["entity_type_id"], ["entitytype.id"]),
        sa.UniqueConstraint("entity_type_id", "value"),
    )

    op.create_table(
        "entityvaluealias",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("entity_value_id", sa.Integer(), nullable=False),
        sa.Column("phrase", sa.String(length=500), nullable=False),
        sa.Column("normalized_phrase", sa.String(length=500), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["entity_value_id"], ["entityvalue.id"]),
    )
    op.create_index(
        op.f("ix_entityvaluealias_normalized_phrase"),
        "entityvaluealias",
        ["normalized_phrase"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_entityvaluealias_normalized_phrase"), table_name="entityvaluealias")
    op.drop_table("entityvaluealias")
    op.drop_table("entityvalue")
    op.drop_index(op.f("ix_commandexample_normalized_phrase"), table_name="commandexample")
    op.drop_table("commandexample")
    op.drop_table("auditlog")
    op.drop_index(op.f("ix_appsetting_key"), table_name="appsetting")
    op.drop_table("appsetting")
    op.drop_index(op.f("ix_catalogversion_version_number"), table_name="catalogversion")
    op.drop_table("catalogversion")
    op.drop_table("normalizationlog")
    op.drop_index(op.f("ix_entitytype_code"), table_name="entitytype")
    op.drop_table("entitytype")
    op.drop_index(op.f("ix_commanddefinition_code"), table_name="commanddefinition")
    op.drop_table("commanddefinition")
    op.drop_index(op.f("ix_adminuser_email"), table_name="adminuser")
    op.drop_table("adminuser")

    setting_value_type_enum.drop(op.get_bind(), checkfirst=True)
    catalog_status_enum.drop(op.get_bind(), checkfirst=True)
    review_status_enum.drop(op.get_bind(), checkfirst=True)
    example_source_enum.drop(op.get_bind(), checkfirst=True)
    match_type_enum.drop(op.get_bind(), checkfirst=True)
    command_name_enum.drop(op.get_bind(), checkfirst=True)
    user_role_enum.drop(op.get_bind(), checkfirst=True)
