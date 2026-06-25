"""expand admin roles

Revision ID: 20260625_0002
Revises: 20260624_0001
Create Date: 2026-06-25 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260625_0002"
down_revision = "20260624_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            "ALTER TABLE adminuser MODIFY COLUMN role "
            "ENUM('admin','editor','viewer') NOT NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "mysql":
        op.execute(
            "ALTER TABLE adminuser MODIFY COLUMN role "
            "ENUM('admin') NOT NULL"
        )
