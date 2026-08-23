"""add return snapshot columns

Revision ID: 20260822_20
Revises: 20260822_19

NOTE: 退货价值快照（refund_unit_price_snapshot / return_unit_cost_snapshot）
对于本迁移之前已存在的 OrderReturn 记录，字段值为 NULL。
剩余池算法在计算时跳过 snapshot 为 NULL 的历史退货，不会扣除其消费的价值。
因此：升级前产生的开发期退货记录不保证 remaining-pool 历史价值重建，
正式上线前应使用干净业务库（从 migration head 全新建库）。
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_20"
down_revision = "20260822_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    columns = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("order_returns")}
    if "refund_unit_price_snapshot" not in columns:
        op.add_column(
            "order_returns",
            sa.Column("refund_unit_price_snapshot", sa.Numeric(18, 2, asdecimal=False), nullable=True, server_default=None),
        )
    if "return_unit_cost_snapshot" not in columns:
        op.add_column(
            "order_returns",
            sa.Column("return_unit_cost_snapshot", sa.Numeric(18, 2, asdecimal=False), nullable=True, server_default=None),
        )


def downgrade() -> None:
    op.drop_column("order_returns", "return_unit_cost_snapshot")
    op.drop_column("order_returns", "refund_unit_price_snapshot")
