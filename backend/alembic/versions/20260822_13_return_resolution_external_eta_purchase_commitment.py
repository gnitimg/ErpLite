"""add return resolution, external processing ETA, and purchase commitments

Revision ID: 20260822_13
Revises: 20260822_12
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_13"
down_revision = "20260822_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    item_columns = {c["name"] for c in inspector.get_columns("inventory_items")}
    return_columns = {c["name"] for c in inspector.get_columns("order_returns")}
    ext_columns = {c["name"] for c in inspector.get_columns("external_processing_batches")}
    table_names = set(inspector.get_table_names())

    if "default_external_lead_days" not in item_columns:
        op.add_column(
            "inventory_items",
            sa.Column("default_external_lead_days", sa.Integer(), nullable=False, server_default="0"),
        )

    if "resolution" not in return_columns:
        op.add_column(
            "order_returns",
            sa.Column("resolution", sa.String(length=20), nullable=False, server_default="REFUND"),
        )

    if "expected_return_at" not in ext_columns:
        op.add_column(
            "external_processing_batches",
            sa.Column("expected_return_at", sa.DateTime(), nullable=True),
        )

    if "purchase_commitments" not in table_names:
        op.create_table(
            "purchase_commitments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("part_id", sa.Integer(), sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"), nullable=False),
            sa.Column("quantity", sa.Float(), nullable=False),
            sa.Column("expected_arrival_at", sa.DateTime(), nullable=False),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="PLANNED"),
            sa.Column("supplier_text", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_purchase_commitments_part_id", "purchase_commitments", ["part_id"])
        op.create_index("ix_purchase_commitments_status", "purchase_commitments", ["status"])
        op.create_index("ix_purchase_commitments_expected_arrival_at", "purchase_commitments", ["expected_arrival_at"])


def downgrade() -> None:
    op.drop_index("ix_purchase_commitments_expected_arrival_at", table_name="purchase_commitments")
    op.drop_index("ix_purchase_commitments_status", table_name="purchase_commitments")
    op.drop_index("ix_purchase_commitments_part_id", table_name="purchase_commitments")
    op.drop_table("purchase_commitments")
    op.drop_column("external_processing_batches", "expected_return_at")
    op.drop_column("order_returns", "resolution")
    op.drop_column("inventory_items", "default_external_lead_days")
