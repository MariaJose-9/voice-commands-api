"""create command parameters

Revision ID: 20260708_0005
Revises: 20260708_0004
Create Date: 2026-07-08 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260708_0005"
down_revision = "20260708_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "commandparameter",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("command_id", sa.Integer(), nullable=False),
        sa.Column("slot_name", sa.String(length=255), nullable=False),
        sa.Column("entity_type_id", sa.Integer(), nullable=False),
        sa.Column("target_field", sa.String(length=255), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False),
        sa.Column("allow_multiple", sa.Boolean(), nullable=False),
        sa.Column("default_value", sa.String(length=1024), nullable=True),
        sa.Column("description", sa.String(length=1024), nullable=True),
        sa.Column("extraction_hint", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["command_id"], ["commanddefinition.id"]),
        sa.ForeignKeyConstraint(["entity_type_id"], ["entitytype.id"]),
        sa.UniqueConstraint("command_id", "slot_name"),
    )
    op.create_index(
        op.f("ix_commandparameter_command_id"),
        "commandparameter",
        ["command_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_commandparameter_entity_type_id"),
        "commandparameter",
        ["entity_type_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_commandparameter_entity_type_id"),
        table_name="commandparameter",
    )
    op.drop_index(
        op.f("ix_commandparameter_command_id"),
        table_name="commandparameter",
    )
    op.drop_table("commandparameter")
