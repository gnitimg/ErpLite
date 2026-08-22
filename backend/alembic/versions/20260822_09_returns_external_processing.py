"""add returns and external processing flow

Revision ID: 20260822_09
Revises: 20260821_08
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_09"
down_revision = "20260821_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    inventory_columns = {
        column["name"] for column in inspector.get_columns("inventory_items")
    }
    if "semi_finished_qty" not in inventory_columns:
        op.add_column(
            "inventory_items",
            sa.Column("semi_finished_qty", sa.Integer(), nullable=False, server_default="0"),
        )
    if "processing_qty" not in inventory_columns:
        op.add_column(
            "inventory_items",
            sa.Column("processing_qty", sa.Integer(), nullable=False, server_default="0"),
        )
    if "requires_external_processing" not in inventory_columns:
        op.add_column(
            "inventory_items",
            sa.Column(
                "requires_external_processing",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
    if "external_process_name" not in inventory_columns:
        op.add_column(
            "inventory_items",
            sa.Column(
                "external_process_name",
                sa.String(length=120),
                nullable=False,
                server_default="",
            ),
        )
    inventory_indexes = {
        index["name"] for index in inspector.get_indexes("inventory_items")
    }
    if "ix_inventory_items_requires_external_processing" not in inventory_indexes:
        op.create_index(
            "ix_inventory_items_requires_external_processing",
            "inventory_items",
            ["requires_external_processing"],
        )
    order_item_columns = {
        column["name"] for column in inspector.get_columns("sales_order_items")
    }
    if "returned_quantity" not in order_item_columns:
        op.add_column(
            "sales_order_items",
            sa.Column("returned_quantity", sa.Integer(), nullable=False, server_default="0"),
        )
    if "pipeline_quantity" not in order_item_columns:
        op.add_column(
            "sales_order_items",
            sa.Column("pipeline_quantity", sa.Integer(), nullable=False, server_default="0"),
        )
    op.create_table(
        "order_returns",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("return_no", sa.String(length=50), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("restocked", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("transaction_id", sa.Integer(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["order_id"], ["sales_orders.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["order_item_id"], ["sales_order_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["product_id"], ["inventory_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["transaction_id"], ["stock_transactions.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_order_returns_return_no", "order_returns", ["return_no"])
    op.create_index("ix_order_returns_order_id", "order_returns", ["order_id"])
    op.create_index("ix_order_returns_order_item_id", "order_returns", ["order_item_id"])
    op.create_index("ix_order_returns_product_id", "order_returns", ["product_id"])
    op.create_index("ix_order_returns_transaction_id", "order_returns", ["transaction_id"])
    op.create_index("ix_order_returns_occurred_at", "order_returns", ["occurred_at"])
    op.create_index("ix_order_returns_order_time", "order_returns", ["order_id", "occurred_at"])
    op.create_table(
        "external_processing_batches",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("batch_no", sa.String(length=50), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("process_name_snapshot", sa.String(length=120), nullable=False),
        sa.Column("supplier", sa.String(length=120), nullable=False, server_default=""),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("returned_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="SENT"),
        sa.Column("outbound_transaction_id", sa.Integer(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.Column("returned_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["inventory_items.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["outbound_transaction_id"],
            ["stock_transactions.id"],
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_external_processing_batches_batch_no",
        "external_processing_batches",
        ["batch_no"],
        unique=True,
    )
    op.create_index(
        "ix_external_processing_batches_product_id",
        "external_processing_batches",
        ["product_id"],
    )
    op.create_index(
        "ix_external_processing_batches_status",
        "external_processing_batches",
        ["status"],
    )
    op.create_index(
        "ix_external_processing_batches_outbound_transaction_id",
        "external_processing_batches",
        ["outbound_transaction_id"],
    )
    op.create_index(
        "ix_external_processing_batches_sent_at",
        "external_processing_batches",
        ["sent_at"],
    )
    op.create_index(
        "ix_external_batches_status_sent",
        "external_processing_batches",
        ["status", "sent_at"],
    )


def downgrade() -> None:
    op.drop_table("external_processing_batches")
    op.drop_table("order_returns")
    op.drop_column("sales_order_items", "pipeline_quantity")
    op.drop_column("sales_order_items", "returned_quantity")
    op.drop_index(
        "ix_inventory_items_requires_external_processing",
        table_name="inventory_items",
    )
    op.drop_column("inventory_items", "external_process_name")
    op.drop_column("inventory_items", "requires_external_processing")
    op.drop_column("inventory_items", "processing_qty")
    op.drop_column("inventory_items", "semi_finished_qty")
