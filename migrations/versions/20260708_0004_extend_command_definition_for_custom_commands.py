"""extend command definition for custom commands

Revision ID: 20260708_0004
Revises: 20260626_0003
Create Date: 2026-07-08 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260708_0004"
down_revision = "20260626_0003"
branch_labels = None
depends_on = None


COMMAND_NAME_VALUES = (
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
)


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "mysql":
        op.execute("ALTER TABLE commanddefinition MODIFY COLUMN code VARCHAR(255) NOT NULL")
    elif dialect != "sqlite":
        op.alter_column(
            "commanddefinition",
            "code",
            existing_type=sa.Enum(*COMMAND_NAME_VALUES, name="commandname"),
            type_=sa.String(length=255),
            existing_nullable=False,
        )

    op.add_column(
        "commanddefinition",
        sa.Column(
            "command_type",
            sa.String(length=32),
            nullable=False,
            server_default="core",
        ),
    )
    op.add_column(
        "commanddefinition",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
    )
    op.add_column(
        "commanddefinition",
        sa.Column(
            "protected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
    )
    op.add_column(
        "commanddefinition",
        sa.Column("client_action_key", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "commanddefinition",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "commanddefinition",
        sa.Column("created_by", sa.Integer(), nullable=True),
    )
    op.add_column(
        "commanddefinition",
        sa.Column("updated_by", sa.Integer(), nullable=True),
    )
    if dialect != "sqlite":
        op.create_foreign_key(
            "fk_commanddefinition_created_by_adminuser",
            "commanddefinition",
            "adminuser",
            ["created_by"],
            ["id"],
        )
        op.create_foreign_key(
            "fk_commanddefinition_updated_by_adminuser",
            "commanddefinition",
            "adminuser",
            ["updated_by"],
            ["id"],
        )

    op.execute(
        "UPDATE commanddefinition "
        "SET command_type = 'core', status = 'active', protected = 1, "
        "client_action_key = LOWER(code) "
        "WHERE client_action_key IS NULL"
    )

    op.alter_column("commanddefinition", "command_type", server_default=None)
    op.alter_column("commanddefinition", "status", server_default=None)
    op.alter_column("commanddefinition", "protected", server_default=None)


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect != "sqlite":
        op.drop_constraint(
            "fk_commanddefinition_updated_by_adminuser",
            "commanddefinition",
            type_="foreignkey",
        )
        op.drop_constraint(
            "fk_commanddefinition_created_by_adminuser",
            "commanddefinition",
            type_="foreignkey",
        )
    op.drop_column("commanddefinition", "updated_by")
    op.drop_column("commanddefinition", "created_by")
    op.drop_column("commanddefinition", "deleted_at")
    op.drop_column("commanddefinition", "client_action_key")
    op.drop_column("commanddefinition", "protected")
    op.drop_column("commanddefinition", "status")
    op.drop_column("commanddefinition", "command_type")

    if dialect == "mysql":
        values = ", ".join(f"'{value}'" for value in COMMAND_NAME_VALUES)
        op.execute(
            "ALTER TABLE commanddefinition MODIFY COLUMN code "
            f"ENUM({values}) NOT NULL"
        )
    elif dialect != "sqlite":
        op.alter_column(
            "commanddefinition",
            "code",
            existing_type=sa.String(length=255),
            type_=sa.Enum(*COMMAND_NAME_VALUES, name="commandname"),
            existing_nullable=False,
        )
