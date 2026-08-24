"""move daily capacity onto products

Revision ID: 20260821_06
Revises: 20260821_05
Create Date: 2026-08-21
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260821_06"
down_revision: Union[str, None] = "20260821_05"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    items = sa.table(
        "inventory_items",
        sa.column("id", sa.Integer()),
        sa.column("kind", sa.String()),
        sa.column("daily_capacity", sa.Float()),
    )
    capabilities = sa.table(
        "production_capabilities",
        sa.column("product_id", sa.Integer()),
        sa.column("nominal_daily_capacity", sa.Integer()),
        sa.column("active", sa.Boolean()),
    )
    legacy_capacity = {
        int(product_id): int(capacity or 0)
        for product_id, capacity in bind.execute(
            sa.select(
                capabilities.c.product_id,
                sa.func.max(capabilities.c.nominal_daily_capacity),
            )
            .where(capabilities.c.active.is_(True))
            .group_by(capabilities.c.product_id)
        )
    }
    for product_id, capacity in legacy_capacity.items():
        bind.execute(
            items.update()
            .where(
                items.c.id == product_id,
                items.c.kind == "PRODUCT",
                items.c.daily_capacity <= 0,
            )
            .values(daily_capacity=capacity)
        )

    column = next(
        c for c in sa.inspect(bind).get_columns("inventory_items")
        if c["name"] == "daily_capacity"
    )
    if not isinstance(column["type"], sa.Integer):
        with op.batch_alter_table("inventory_items") as batch_op:
            batch_op.alter_column(
                "daily_capacity",
                existing_type=column["type"],
                type_=sa.Integer(),
                existing_nullable=column["nullable"],
                existing_server_default=column.get("default"),
            )


def downgrade() -> None:
    with op.batch_alter_table("inventory_items") as batch_op:
        batch_op.alter_column(
            "daily_capacity",
            existing_type=sa.Integer(),
            type_=sa.Float(),
            existing_nullable=False,
            existing_server_default=sa.text("0"),
        )
