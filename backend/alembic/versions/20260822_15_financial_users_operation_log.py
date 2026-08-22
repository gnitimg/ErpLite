"""add financial closing, user permissions, and operation log business summary

Revision ID: 20260822_15
Revises: 20260822_14
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_15"
down_revision = "20260822_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    log_columns = {c["name"] for c in inspector.get_columns("operation_logs")}
    table_names = set(inspector.get_table_names())

    if "business_summary" not in log_columns:
        op.add_column(
            "operation_logs",
            sa.Column("business_summary", sa.String(length=500), nullable=False, server_default=""),
        )

    if "receivables" not in table_names:
        op.create_table(
            "receivables",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("receivable_no", sa.String(length=50), nullable=False),
            sa.Column("order_id", sa.Integer(), sa.ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("customer_name", sa.String(length=120), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2, asdecimal=False), nullable=False, server_default="0"),
            sa.Column("settled_amount", sa.Numeric(18, 2, asdecimal=False), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="OPEN"),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("receivable_no", name="uq_receivables_no"),
        )
        op.create_index("ix_receivables_order_id", "receivables", ["order_id"])
        op.create_index("ix_receivables_customer_name", "receivables", ["customer_name"])
        op.create_index("ix_receivables_status", "receivables", ["status"])
        op.create_index("ix_receivables_status_created", "receivables", ["status", "created_at"])

    if "payments" not in table_names:
        op.create_table(
            "payments",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("payment_no", sa.String(length=50), nullable=False),
            sa.Column("customer_name", sa.String(length=120), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2, asdecimal=False), nullable=False, server_default="0"),
            sa.Column("allocated_amount", sa.Numeric(18, 2, asdecimal=False), nullable=False, server_default="0"),
            sa.Column("payment_date", sa.Date(), nullable=False, server_default=sa.func.current_date()),
            sa.Column("method", sa.String(length=20), nullable=False, server_default="TRANSFER"),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("payment_no", name="uq_payments_no"),
        )
        op.create_index("ix_payments_customer_name", "payments", ["customer_name"])
        op.create_index("ix_payments_payment_date", "payments", ["payment_date"])
        op.create_index("ix_payments_customer_date", "payments", ["customer_name", "payment_date"])

    if "payment_allocations" not in table_names:
        op.create_table(
            "payment_allocations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id", ondelete="CASCADE"), nullable=False),
            sa.Column("receivable_id", sa.Integer(), sa.ForeignKey("receivables.id", ondelete="CASCADE"), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2, asdecimal=False), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("payment_id", "receivable_id", name="uq_payment_receivable"),
        )
        op.create_index("ix_payment_allocations_payment_id", "payment_allocations", ["payment_id"])
        op.create_index("ix_payment_allocations_receivable_id", "payment_allocations", ["receivable_id"])

    if "users" not in table_names:
        op.create_table(
            "users",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("username", sa.String(length=60), nullable=False),
            sa.Column("password_hash", sa.String(length=200), nullable=False, server_default=""),
            sa.Column("display_name", sa.String(length=120), nullable=False, server_default=""),
            sa.Column("role", sa.String(length=20), nullable=False, server_default="OPERATOR"),
            sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("username", name="uq_users_username"),
        )
        op.create_index("ix_users_username", "users", ["username"])
        op.create_index("ix_users_role", "users", ["role"])
        op.create_index("ix_users_active", "users", ["active"])


def downgrade() -> None:
    op.drop_index("ix_users_active", table_name="users")
    op.drop_index("ix_users_role", table_name="users")
    op.drop_index("ix_users_username", table_name="users")
    op.drop_table("users")
    op.drop_index("ix_payment_allocations_receivable_id", table_name="payment_allocations")
    op.drop_index("ix_payment_allocations_payment_id", table_name="payment_allocations")
    op.drop_table("payment_allocations")
    op.drop_index("ix_payments_customer_date", table_name="payments")
    op.drop_index("ix_payments_payment_date", table_name="payments")
    op.drop_index("ix_payments_customer_name", table_name="payments")
    op.drop_table("payments")
    op.drop_index("ix_receivables_status_created", table_name="receivables")
    op.drop_index("ix_receivables_status", table_name="receivables")
    op.drop_index("ix_receivables_customer_name", table_name="receivables")
    op.drop_index("ix_receivables_order_id", table_name="receivables")
    op.drop_table("receivables")
    op.drop_column("operation_logs", "business_summary")
