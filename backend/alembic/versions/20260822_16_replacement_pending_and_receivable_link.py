"""add replacement_pending_quantity and receivable stock transaction link

Revision ID: 20260822_16
Revises: 20260822_15
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_16"
down_revision = "20260822_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    item_columns = {c["name"] for c in inspector.get_columns("sales_order_items")}
    recv_columns = {c["name"] for c in inspector.get_columns("receivables")}

    if "replacement_pending_quantity" not in item_columns:
        op.add_column(
            "sales_order_items",
            sa.Column("replacement_pending_quantity", sa.Integer(), nullable=False, server_default="0"),
        )

    if "related_stock_transaction_id" not in recv_columns:
        op.add_column(
            "receivables",
            sa.Column(
                "related_stock_transaction_id",
                sa.Integer(),
                sa.ForeignKey("stock_transactions.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
        op.create_index("ix_receivables_stock_tx", "receivables", ["related_stock_transaction_id"])


def downgrade() -> None:
    op.drop_index("ix_receivables_stock_tx", table_name="receivables")
    op.drop_column("receivables", "related_stock_transaction_id")
    op.drop_column("sales_order_items", "replacement_pending_quantity")
