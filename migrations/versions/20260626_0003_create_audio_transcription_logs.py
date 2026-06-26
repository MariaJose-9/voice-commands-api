"""create audio transcription logs

Revision ID: 20260626_0003
Revises: 20260625_0002
Create Date: 2026-06-26 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260626_0003"
down_revision = "20260625_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audiotranscriptionlog",
        sa.Column("id", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=128), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("language_hint", sa.String(length=32), nullable=True),
        sa.Column("detected_language", sa.String(length=32), nullable=True),
        sa.Column("transcribed_text", sa.String(length=4000), nullable=True),
        sa.Column("duration_seconds", sa.Float(), nullable=True),
        sa.Column("engine", sa.String(length=128), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False),
        sa.Column("error_message", sa.String(length=1024), nullable=True),
        sa.Column("used_for_normalization", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("audiotranscriptionlog")
