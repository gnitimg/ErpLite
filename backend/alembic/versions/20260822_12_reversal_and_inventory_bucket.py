"""add stock transaction reversal and inventory bucket fields

Revision ID: 20260822_12
Revises: 20260822_11
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_12"
down_revision = "20260822_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tx_columns = {c["name"] for c in inspector.get_columns("stock_transactions")}
    item_columns = {c["name"] for c in inspector.get_columns("stock_transaction_items")}
    tx_indexes = {i["name"] for i in inspector.get_indexes("stock_transactions")}

    if "status" not in tx_columns:
        op.add_column(
            "stock_transactions",
            sa.Column("status", sa.String(length=20), nullable=False, server_default="POSTED"),
        )
    if "reversal_of_transaction_id" not in tx_columns:
        op.add_column(
            "stock_transactions",
            sa.Column(
                "reversal_of_transaction_id",
                sa.Integer(),
                sa.ForeignKey("stock_transactions.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "reversed_by_transaction_id" not in tx_columns:
        op.add_column(
            "stock_transactions",
            sa.Column(
                "reversed_by_transaction_id",
                sa.Integer(),
                sa.ForeignKey("stock_transactions.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )
    if "ix_stock_transactions_status" not in tx_indexes:
        op.create_index("ix_stock_transactions_status", "stock_transactions", ["status"])
    if "ix_stock_transactions_reversal_of" not in tx_indexes:
        op.create_index("ix_stock_transactions_reversal_of", "stock_transactions", ["reversal_of_transaction_id"])
    if "ix_stock_transactions_reversed_by" not in tx_indexes:
        op.create_index("ix_stock_transactions_reversed_by", "stock_transactions", ["reversed_by_transaction_id"])

    if "inventory_bucket" not in item_columns:
        op.add_column(
            "stock_transaction_items",
            sa.Column("inventory_bucket", sa.String(length=20), nullable=False, server_default="FINISHED"),
        )
    if "affects_primary_stock" not in item_columns:
        op.add_column(
            "stock_transaction_items",
            sa.Column("affects_primary_stock", sa.Boolean(), nullable=False, server_default="1"),
        )


def downgrade() -> None:
    op.drop_column("stock_transaction_items", "affects_primary_stock")
    op.drop_column("stock_transaction_items", "inventory_bucket")
    op.drop_index("ix_stock_transactions_reversed_by", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_reversal_of", table_name="stock_transactions")
    op.drop_index("ix_stock_transactions_status", table_name="stock_transactions")
    op.drop_column("stock_transactions", "reversed_by_transaction_id")
    op.drop_column("stock_transactions", "reversal_of_transaction_id")
    op.drop_column("stock_transactions", "status")
