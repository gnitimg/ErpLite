"""add customer_credits table

Revision ID: 20260822_19
Revises: 20260822_18
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_19"
down_revision = "20260822_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "customer_credits" not in inspector.get_table_names():
        op.create_table(
            "customer_credits",
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("credit_no", sa.String(50), nullable=False, unique=True),
            sa.Column("order_id", sa.Integer, sa.ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True),
            sa.Column("order_return_id", sa.Integer, sa.ForeignKey("order_returns.id", ondelete="SET NULL"), nullable=True),
            sa.Column("receivable_id", sa.Integer, sa.ForeignKey("receivables.id", ondelete="SET NULL"), nullable=True),
            sa.Column("customer_name", sa.String(120), nullable=False),
            sa.Column("amount", sa.Numeric(18, 2, asdecimal=False), nullable=False, server_default="0"),
            sa.Column("settled_amount", sa.Numeric(18, 2, asdecimal=False), nullable=False, server_default="0"),
            sa.Column("kind", sa.String(20), nullable=False, server_default="REFUND_DUE"),
            sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
            sa.Column("notes", sa.Text, nullable=True),
            sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        )
        op.create_index("ix_customer_credits_credit_no", "customer_credits", ["credit_no"])
        op.create_index("ix_customer_credits_order_id", "customer_credits", ["order_id"])
        op.create_index("ix_customer_credits_order_return_id", "customer_credits", ["order_return_id"])
        op.create_index("ix_customer_credits_receivable_id", "customer_credits", ["receivable_id"])
        op.create_index("ix_customer_credits_customer_name", "customer_credits", ["customer_name"])
        op.create_index("ix_customer_credits_kind", "customer_credits", ["kind"])
        op.create_index("ix_customer_credits_status", "customer_credits", ["status"])
        op.create_index("ix_credits_status_created", "customer_credits", ["status", "created_at"])


def downgrade() -> None:
    op.drop_table("customer_credits")
