"""add manual production scheduling lock

Revision ID: 20260821_04
Revises: 20260820_03
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_04"
down_revision: Union[str, None] = "20260820_03"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    if "schedule_locked" not in _column_names(bind, "production_runs"):
        op.add_column(
            "production_runs",
            sa.Column(
                "schedule_locked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "ix_production_runs_schedule_locked" not in _index_names(
        bind,
        "production_runs",
    ):
        op.create_index(
            "ix_production_runs_schedule_locked",
            "production_runs",
            ["schedule_locked"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if "ix_production_runs_schedule_locked" in _index_names(
        bind,
        "production_runs",
    ):
        op.drop_index(
            "ix_production_runs_schedule_locked",
            table_name="production_runs",
        )
    op.drop_column("production_runs", "schedule_locked")
