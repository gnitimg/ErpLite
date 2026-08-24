"""add production calendar, DECIMAL amounts, and BOM validation

Revision ID: 20260822_14
Revises: 20260822_13
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_14"
down_revision = "20260822_13"
branch_labels = None
depends_on = None


AMOUNT_COLUMNS = [
    ("inventory_items", "cost_price"),
    ("inventory_items", "sale_price"),
    ("sales_orders", "total_amount"),
    ("sales_order_items", "reference_price"),
    ("sales_order_items", "unit_price"),
    ("sales_order_items", "line_total"),
    ("stock_transaction_items", "unit_cost"),
    ("stock_transaction_items", "unit_price_snapshot"),
    ("stock_transaction_items", "line_total_snapshot"),
]


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    settings_columns = {c["name"] for c in inspector.get_columns("production_settings")}
    table_names = set(inspector.get_table_names())

    if "working_weekdays" not in settings_columns:
        op.add_column(
            "production_settings",
            sa.Column("working_weekdays", sa.String(length=20), nullable=False, server_default="1,2,3,4,5"),
        )

    if "production_calendar_exceptions" not in table_names:
        op.create_table(
            "production_calendar_exceptions",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("exception_date", sa.Date(), nullable=False),
            sa.Column("is_working_day", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("note", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("exception_date", name="uq_calendar_exception_date"),
        )
        op.create_index("ix_calendar_exception_date", "production_calendar_exceptions", ["exception_date"])

    bind = op.get_bind()
    for table_name, column_name in AMOUNT_COLUMNS:
        columns = {c["name"] for c in inspector.get_columns(table_name)}
        if column_name in columns:
            column = next(c for c in inspector.get_columns(table_name) if c["name"] == column_name)
            nullable = column_name in ("unit_price_snapshot", "line_total_snapshot")
            current_type = column["type"]
            if not (
                isinstance(current_type, sa.Numeric)
                and current_type.precision == 18
                and current_type.scale == 2
            ):
                op.alter_column(
                    table_name,
                    column_name,
                    existing_type=current_type,
                    type_=sa.Numeric(18, 2, asdecimal=False),
                    existing_nullable=nullable,
                )


def downgrade() -> None:
    op.drop_index("ix_calendar_exception_date", table_name="production_calendar_exceptions")
    op.drop_table("production_calendar_exceptions")
    op.drop_column("production_settings", "working_weekdays")
    for table_name, column_name in AMOUNT_COLUMNS:
        nullable = column_name in ("unit_price_snapshot", "line_total_snapshot")
        op.alter_column(
            table_name,
            column_name,
            existing_type=sa.Numeric(18, 2, asdecimal=False),
            type_=sa.Float(),
            existing_nullable=nullable,
        )
