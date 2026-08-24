"""bind mold capacity directly to products

Revision ID: 20260820_02
Revises: 20260820_01
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260820_02"
down_revision: Union[str, None] = "20260820_01"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def _column(bind, table_name: str, column_name: str) -> dict:
    return next(
        column
        for column in sa.inspect(bind).get_columns(table_name)
        if column["name"] == column_name
    )


def upgrade() -> None:
    bind = op.get_bind()
    if "mold_count" not in _column_names(bind, "inventory_items"):
        op.add_column(
            "inventory_items",
            sa.Column("mold_count", sa.Integer(), nullable=False, server_default="0"),
        )
    if "mold_slot" not in _column_names(bind, "production_runs"):
        op.add_column(
            "production_runs",
            sa.Column("mold_slot", sa.Integer(), nullable=False, server_default="1"),
        )

    bind.execute(sa.text(
        "UPDATE inventory_items SET mold_count = CASE "
        "WHEN kind = 'PRODUCT' THEN CASE WHEN ("
        "SELECT COUNT(*) FROM product_molds "
        "WHERE product_molds.product_id = inventory_items.id "
        "AND product_molds.active = 1"
        ") > 0 THEN ("
        "SELECT COUNT(*) FROM product_molds "
        "WHERE product_molds.product_id = inventory_items.id "
        "AND product_molds.active = 1"
        ") ELSE 1 END ELSE 0 END"
    ))
    bind.execute(sa.text(
        "UPDATE production_capabilities SET active = 0 WHERE id NOT IN ("
        "SELECT keep_id FROM ("
        "SELECT MIN(id) AS keep_id FROM production_capabilities "
        "GROUP BY product_id, line_id"
        ") AS kept)"
    ))

    capability_mold = _column(bind, "production_capabilities", "mold_id")
    run_mold = _column(bind, "production_runs", "mold_id")
    if bind.dialect.name == "sqlite" and (
        not capability_mold["nullable"] or not run_mold["nullable"]
    ):
        with op.batch_alter_table("production_capabilities") as batch:
            if not capability_mold["nullable"]:
                batch.alter_column("mold_id", existing_type=sa.Integer(), nullable=True)
        with op.batch_alter_table("production_runs") as batch:
            if not run_mold["nullable"]:
                batch.alter_column("mold_id", existing_type=sa.Integer(), nullable=True)
    else:
        if not capability_mold["nullable"]:
            op.alter_column(
                "production_capabilities", "mold_id",
                existing_type=capability_mold["type"], nullable=True,
            )
        if not run_mold["nullable"]:
            op.alter_column(
                "production_runs", "mold_id",
                existing_type=run_mold["type"], nullable=True,
            )
    bind.execute(sa.text("UPDATE production_capabilities SET mold_id = NULL"))
    bind.execute(sa.text("UPDATE production_runs SET mold_slot = 1"))

    if "ix_capability_product_line" not in _index_names(bind, "production_capabilities"):
        op.create_index(
            "ix_capability_product_line",
            "production_capabilities",
            ["product_id", "line_id"],
        )
    if "ix_runs_product_mold_slot_status" not in _index_names(bind, "production_runs"):
        op.create_index(
            "ix_runs_product_mold_slot_status",
            "production_runs",
            ["product_id", "mold_slot", "status"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO molds (code, name, active, created_at, updated_at) "
        "SELECT 'LEGACY-MOLD', '兼容模具', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "WHERE NOT EXISTS (SELECT 1 FROM molds WHERE code = 'LEGACY-MOLD')"
    ))
    legacy_mold_id = bind.execute(sa.text(
        "SELECT id FROM molds WHERE code = 'LEGACY-MOLD'"
    )).scalar_one()
    bind.execute(
        sa.text("UPDATE production_capabilities SET mold_id = :mold_id WHERE mold_id IS NULL"),
        {"mold_id": legacy_mold_id},
    )
    bind.execute(
        sa.text("UPDATE production_runs SET mold_id = :mold_id WHERE mold_id IS NULL"),
        {"mold_id": legacy_mold_id},
    )
    if "ix_runs_product_mold_slot_status" in _index_names(bind, "production_runs"):
        op.drop_index("ix_runs_product_mold_slot_status", table_name="production_runs")
    if "ix_capability_product_line" in _index_names(bind, "production_capabilities"):
        op.drop_index("ix_capability_product_line", table_name="production_capabilities")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("production_runs") as batch:
            batch.alter_column("mold_id", existing_type=sa.Integer(), nullable=False)
            batch.drop_column("mold_slot")
        with op.batch_alter_table("production_capabilities") as batch:
            batch.alter_column("mold_id", existing_type=sa.Integer(), nullable=False)
    else:
        op.alter_column(
            "production_runs",
            "mold_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        op.drop_column("production_runs", "mold_slot")
        op.alter_column(
            "production_capabilities",
            "mold_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    op.drop_column("inventory_items", "mold_count")
