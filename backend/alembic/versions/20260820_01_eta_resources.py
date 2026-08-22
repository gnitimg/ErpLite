"""add ETA production resources and planning data

Revision ID: 20260820_01
Revises:
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from app.database import Base
from app import models


revision: str = "20260820_01"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _add_column_if_missing(inspector, table_name: str, column: sa.Column) -> None:
    columns = {item["name"] for item in inspector.get_columns(table_name)}
    if column.name not in columns:
        op.add_column(table_name, column)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "inventory_items" not in tables:
        Base.metadata.create_all(bind=bind)
        return

    _add_column_if_missing(
        inspector,
        "sales_orders",
        sa.Column("estimated_completion_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        inspector,
        "sales_orders",
        sa.Column("eta_calculated_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        inspector,
        "sales_orders",
        sa.Column("eta_reliable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        inspector,
        "sales_orders",
        sa.Column("eta_note", sa.String(length=500), nullable=False, server_default=""),
    )
    _add_column_if_missing(
        inspector,
        "sales_order_items",
        sa.Column("production_required_quantity", sa.Float(), nullable=False, server_default="0"),
    )
    _add_column_if_missing(
        inspector,
        "sales_order_items",
        sa.Column("estimated_completion_at", sa.DateTime(), nullable=True),
    )
    _add_column_if_missing(
        inspector,
        "sales_order_items",
        sa.Column("eta_reliable", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    _add_column_if_missing(
        inspector,
        "sales_order_items",
        sa.Column("eta_note", sa.String(length=500), nullable=False, server_default=""),
    )

    for table in (
        models.ProductionLine.__table__,
        models.Mold.__table__,
        models.ProductMold.__table__,
        models.ProductionCapability.__table__,
        models.StockReservation.__table__,
        models.ProductionRun.__table__,
        models.ProductionAllocation.__table__,
    ):
        table.create(bind=bind, checkfirst=True)

    existing_indexes = {index["name"] for index in sa.inspect(bind).get_indexes("sales_orders")}
    if "ix_orders_status_required" not in existing_indexes:
        op.create_index(
            "ix_orders_status_required",
            "sales_orders",
            ["status", "required_date"],
        )
    if "ix_sales_orders_estimated_completion_at" not in existing_indexes:
        op.create_index(
            "ix_sales_orders_estimated_completion_at",
            "sales_orders",
            ["estimated_completion_at"],
        )

    bind.execute(sa.text(
        "INSERT INTO stock_reservations "
        "(order_item_id, product_id, quantity, status, created_at, updated_at) "
        "SELECT item.id, item.product_id, item.reserved_quantity, "
        "CASE WHEN item.reserved_quantity > 0 THEN 'ACTIVE' ELSE 'RELEASED' END, "
        "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "FROM sales_order_items AS item "
        "WHERE NOT EXISTS ("
        "SELECT 1 FROM stock_reservations AS reservation "
        "WHERE reservation.order_item_id = item.id)"
    ))


def downgrade() -> None:
    bind = op.get_bind()
    for table_name in (
        "production_allocations",
        "production_runs",
        "stock_reservations",
        "production_capabilities",
        "product_molds",
        "molds",
        "production_lines",
    ):
        sa.Table(table_name, sa.MetaData()).drop(bind=bind, checkfirst=True)
    for table_name, column_name in (
        ("sales_order_items", "eta_note"),
        ("sales_order_items", "eta_reliable"),
        ("sales_order_items", "estimated_completion_at"),
        ("sales_order_items", "production_required_quantity"),
        ("sales_orders", "eta_note"),
        ("sales_orders", "eta_reliable"),
        ("sales_orders", "eta_calculated_at"),
        ("sales_orders", "estimated_completion_at"),
    ):
        op.drop_column(table_name, column_name)
