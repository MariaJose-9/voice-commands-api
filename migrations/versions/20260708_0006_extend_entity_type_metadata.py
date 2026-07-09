"""extend entity type metadata

Revision ID: 20260708_0006
Revises: 20260708_0005
Create Date: 2026-07-08 00:00:00
"""

from __future__ import annotations

from datetime import datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = "20260708_0006"
down_revision = "20260708_0005"
branch_labels = None
depends_on = None


def _bool_literal(value: bool) -> str:
    return "1" if value else "0"


def upgrade() -> None:
    op.add_column(
        "entitytype",
        sa.Column(
            "data_type",
            sa.String(length=32),
            nullable=False,
            server_default="string",
        ),
    )
    op.add_column("entitytype", sa.Column("unit", sa.String(length=64), nullable=True))
    op.add_column(
        "entitytype",
        sa.Column(
            "protected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column(
        "entitytype",
        sa.Column(
            "dynamic_values",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.add_column("entitytype", sa.Column("min_value", sa.Float(), nullable=True))
    op.add_column("entitytype", sa.Column("max_value", sa.Float(), nullable=True))
    op.add_column(
        "entitytype",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )

    op.execute(
        "UPDATE entitytype SET data_type = 'enum', protected = 1 "
        "WHERE code IN ('monitor', 'layout')"
    )
    op.execute(
        "UPDATE entitytype SET data_type = 'integer', unit = 'inches', "
        "protected = 1, dynamic_values = 1, min_value = 40, max_value = 150 "
        "WHERE code = 'size_inches'"
    )

    bind = op.get_bind()
    entitytype = sa.table(
        "entitytype",
        sa.column("code", sa.String),
        sa.column("display_name", sa.String),
        sa.column("description", sa.String),
        sa.column("data_type", sa.String),
        sa.column("unit", sa.String),
        sa.column("protected", sa.Boolean),
        sa.column("dynamic_values", sa.Boolean),
        sa.column("min_value", sa.Float),
        sa.column("max_value", sa.Float),
        sa.column("enabled", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(timezone.utc)
    existing_codes = {
        row[0]
        for row in bind.execute(sa.text("SELECT code FROM entitytype")).fetchall()
    }
    if "angle_degrees" not in existing_codes:
        op.bulk_insert(
            entitytype,
            [
                {
                    "code": "angle_degrees",
                    "display_name": "Angle Degrees",
                    "description": None,
                    "data_type": "integer",
                    "unit": "degrees",
                    "protected": False,
                    "dynamic_values": True,
                    "min_value": 0,
                    "max_value": 360,
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )
    if "distance" not in existing_codes:
        op.bulk_insert(
            entitytype,
            [
                {
                    "code": "distance",
                    "display_name": "Distance",
                    "description": None,
                    "data_type": "float",
                    "unit": "meter",
                    "protected": False,
                    "dynamic_values": True,
                    "min_value": None,
                    "max_value": None,
                    "enabled": True,
                    "created_at": now,
                    "updated_at": now,
                }
            ],
        )

    op.alter_column("entitytype", "data_type", server_default=None)
    op.alter_column("entitytype", "protected", server_default=None)
    op.alter_column("entitytype", "dynamic_values", server_default=None)


def downgrade() -> None:
    op.execute("DELETE FROM entitytype WHERE code IN ('angle_degrees', 'distance')")
    op.drop_column("entitytype", "deleted_at")
    op.drop_column("entitytype", "max_value")
    op.drop_column("entitytype", "min_value")
    op.drop_column("entitytype", "dynamic_values")
    op.drop_column("entitytype", "protected")
    op.drop_column("entitytype", "unit")
    op.drop_column("entitytype", "data_type")
