"""add manual production run source and notes

Revision ID: 20260822_10
Revises: 20260822_09
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_10"
down_revision = "20260822_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {
        column["name"] for column in inspector.get_columns("production_runs")
    }
    if "source_type" not in columns:
        op.add_column(
            "production_runs",
            sa.Column(
                "source_type",
                sa.String(length=20),
                nullable=False,
                server_default="ORDER",
            ),
        )
    if "notes" not in columns:
        op.add_column(
            "production_runs",
            sa.Column("notes", sa.Text(), nullable=True),
        )
        op.execute(
            sa.text("UPDATE production_runs SET notes = '' WHERE notes IS NULL")
        )
        op.alter_column(
            "production_runs",
            "notes",
            existing_type=sa.Text(),
            nullable=False,
        )
    indexes = {
        index["name"] for index in inspector.get_indexes("production_runs")
    }
    if "ix_production_runs_source_type" not in indexes:
        op.create_index(
            "ix_production_runs_source_type",
            "production_runs",
            ["source_type"],
        )


def downgrade() -> None:
    op.drop_index("ix_production_runs_source_type", table_name="production_runs")
    op.drop_column("production_runs", "notes")
    op.drop_column("production_runs", "source_type")
