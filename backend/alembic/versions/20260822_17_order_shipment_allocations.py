"""add order_shipment_allocations for ORIGINAL/REPLACEMENT fulfillment

Revision ID: 20260822_17
Revises: 20260822_16
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_17"
down_revision = "20260822_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "order_shipment_allocations" not in set(sa.inspect(bind).get_table_names()):
        op.create_table(
            "order_shipment_allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "order_item_id",
                sa.Integer(),
                sa.ForeignKey("sales_order_items.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "stock_transaction_id",
                sa.Integer(),
                sa.ForeignKey("stock_transactions.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column("fulfillment_type", sa.String(20), nullable=False, server_default="ORIGINAL"),
            sa.Column("quantity", sa.Integer(), nullable=False),
            sa.Column("unit_price_snapshot", sa.Numeric(18, 2, asdecimal=False), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        )
    item_columns = {c["name"] for c in sa.inspect(bind).get_columns("sales_order_items")}
    if "replacement_shipped_quantity" not in item_columns:
        op.add_column(
            "sales_order_items",
            sa.Column("replacement_shipped_quantity", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    op.drop_table("order_shipment_allocations")
    op.drop_column("sales_order_items", "replacement_shipped_quantity")
