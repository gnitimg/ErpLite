"""add scheduling auto snap setting

Revision ID: 20260821_05
Revises: 20260821_04
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_05"
down_revision: Union[str, None] = "20260821_04"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "schedule_auto_snap" not in _column_names(bind, "production_settings"):
        op.add_column(
            "production_settings",
            sa.Column(
                "schedule_auto_snap",
                sa.Boolean(),
                nullable=False,
                server_default=sa.true(),
            ),
        )


def downgrade() -> None:
    op.drop_column("production_settings", "schedule_auto_snap")
