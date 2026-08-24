"""partial shipment and immutable stock document snapshots

Revision ID: 20260821_07
Revises: 20260821_06
"""

from alembic import op
import sqlalchemy as sa


revision = "20260821_07"
down_revision = "20260821_06"
branch_labels = None
depends_on = None


def _columns(bind, table_name: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table_name)}


def _indexes(bind, table_name: str) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(table_name)}


def _has_foreign_key(
    bind, table_name: str, columns: list[str], referred_table: str
) -> bool:
    return any(
        fk.get("constrained_columns") == columns
        and fk.get("referred_table") == referred_table
        for fk in sa.inspect(bind).get_foreign_keys(table_name)
    )


def upgrade() -> None:
    bind = op.get_bind()
    if "shipped_quantity" not in _columns(bind, "sales_order_items"):
        op.add_column(
            "sales_order_items",
            sa.Column("shipped_quantity", sa.Integer(), nullable=False, server_default="0"),
        )
    # 旧版只有整单出库；FULFILLED 可保守地回填为全部已出库。
    op.execute(sa.text(
        "UPDATE sales_order_items SET shipped_quantity = CAST(quantity AS SIGNED) "
        "WHERE order_id IN (SELECT id FROM sales_orders WHERE status = 'FULFILLED')"
    ))
    for name, column_type in (
        ("related_production_run_id", sa.Integer()),
        ("order_no_snapshot", sa.String(50)),
        ("counterparty_name_snapshot", sa.String(120)),
        ("counterparty_phone_snapshot", sa.String(40)),
        ("counterparty_address_snapshot", sa.String(255)),
        ("operator_snapshot", sa.String(120)),
    ):
        if name not in _columns(bind, "stock_transactions"):
            op.add_column("stock_transactions", sa.Column(name, column_type, nullable=True))
    if "ix_stock_transactions_related_production_run_id" not in _indexes(bind, "stock_transactions"):
        op.create_index(
            "ix_stock_transactions_related_production_run_id",
            "stock_transactions", ["related_production_run_id"],
        )
    if not _has_foreign_key(
        bind, "stock_transactions", ["related_production_run_id"], "production_runs"
    ):
        op.create_foreign_key(
            "fk_stock_transactions_production_run", "stock_transactions",
            "production_runs", ["related_production_run_id"], ["id"],
            ondelete="SET NULL",
        )
    for name, column_type in (
        ("sku_snapshot", sa.String(50)),
        ("name_snapshot", sa.String(120)),
        ("spec_snapshot", sa.String(200)),
        ("unit_snapshot", sa.String(20)),
        ("unit_price_snapshot", sa.Float()),
        ("line_total_snapshot", sa.Float()),
    ):
        if name not in _columns(bind, "stock_transaction_items"):
            op.add_column("stock_transaction_items", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name in (
        "line_total_snapshot",
        "unit_price_snapshot",
        "unit_snapshot",
        "spec_snapshot",
        "name_snapshot",
        "sku_snapshot",
    ):
        op.drop_column("stock_transaction_items", name)
    op.drop_constraint("fk_stock_transactions_production_run", "stock_transactions", type_="foreignkey")
    op.drop_index("ix_stock_transactions_related_production_run_id", table_name="stock_transactions")
    for name in (
        "operator_snapshot",
        "counterparty_address_snapshot",
        "counterparty_phone_snapshot",
        "counterparty_name_snapshot",
        "order_no_snapshot",
        "related_production_run_id",
    ):
        op.drop_column("stock_transactions", name)
    op.drop_column("sales_order_items", "shipped_quantity")
