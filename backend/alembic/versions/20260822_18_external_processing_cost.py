"""add external processing_cost

Revision ID: 20260822_18
Revises: 20260822_17
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_18"
down_revision = "20260822_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("external_processing_batches")}
    if "processing_cost" not in columns:
        op.add_column(
            "external_processing_batches",
            sa.Column("processing_cost", sa.Numeric(18, 2, asdecimal=False), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_column("external_processing_batches", "processing_cost")
