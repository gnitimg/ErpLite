"""replace production line records with global line slots

Revision ID: 20260820_03
Revises: 20260820_02
Create Date: 2026-08-20
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "20260820_03"
down_revision: Union[str, None] = "20260820_02"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _index_names(bind, table_name: str) -> set[str]:
    return {index["name"] for index in sa.inspect(bind).get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "production_settings" not in inspector.get_table_names():
        op.create_table(
            "production_settings",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("line_count", sa.Integer(), nullable=False, server_default="1"),
            sa.Column(
                "updated_at",
                sa.DateTime(),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.PrimaryKeyConstraint("id"),
        )
    setting_columns = _column_names(bind, "production_settings")
    snap_column = ", schedule_auto_snap" if "schedule_auto_snap" in setting_columns else ""
    snap_value = ", 1" if "schedule_auto_snap" in setting_columns else ""
    bind.execute(sa.text(
        "INSERT INTO production_settings "
        f"(id, line_count, updated_at{snap_column}) "
        "SELECT 1, CASE WHEN COUNT(*) > 0 THEN COUNT(*) ELSE 1 END, CURRENT_TIMESTAMP "
        f"{snap_value} FROM production_lines WHERE active = 1 "
        "AND NOT EXISTS (SELECT 1 FROM production_settings WHERE id = 1)"
    ))

    if "line_slot" not in _column_names(bind, "production_runs"):
        op.add_column(
            "production_runs",
            sa.Column("line_slot", sa.Integer(), nullable=False, server_default="1"),
        )
    bind.execute(sa.text(
        "UPDATE production_runs SET line_slot = CASE WHEN line_id IS NULL THEN 1 ELSE ("
        "SELECT COUNT(*) FROM production_lines AS known_line "
        "WHERE known_line.id <= production_runs.line_id) END"
    ))
    bind.execute(sa.text(
        "UPDATE production_capabilities SET active = 0 WHERE id NOT IN ("
        "SELECT keep_id FROM ("
        "SELECT MIN(id) AS keep_id FROM production_capabilities GROUP BY product_id"
        ") AS kept)"
    ))

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("production_capabilities") as batch:
            batch.alter_column("line_id", existing_type=sa.Integer(), nullable=True)
        with op.batch_alter_table("production_runs") as batch:
            batch.alter_column("line_id", existing_type=sa.Integer(), nullable=True)
    else:
        op.alter_column(
            "production_capabilities",
            "line_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
        op.alter_column(
            "production_runs",
            "line_id",
            existing_type=sa.Integer(),
            nullable=True,
        )
    bind.execute(sa.text("UPDATE production_capabilities SET line_id = NULL"))
    bind.execute(sa.text("UPDATE production_runs SET line_id = NULL"))

    if "ix_runs_line_slot_status_start" not in _index_names(bind, "production_runs"):
        op.create_index(
            "ix_runs_line_slot_status_start",
            "production_runs",
            ["line_slot", "status", "planned_start_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO production_lines (code, name, active, created_at, updated_at) "
        "SELECT 'LEGACY-LINE', '兼容生产线', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP "
        "WHERE NOT EXISTS (SELECT 1 FROM production_lines)"
    ))
    legacy_line_id = bind.execute(sa.text(
        "SELECT MIN(id) FROM production_lines"
    )).scalar_one()
    bind.execute(
        sa.text(
            "UPDATE production_capabilities SET line_id = :line_id WHERE line_id IS NULL"
        ),
        {"line_id": legacy_line_id},
    )
    bind.execute(
        sa.text("UPDATE production_runs SET line_id = :line_id WHERE line_id IS NULL"),
        {"line_id": legacy_line_id},
    )
    if "ix_runs_line_slot_status_start" in _index_names(bind, "production_runs"):
        op.drop_index("ix_runs_line_slot_status_start", table_name="production_runs")
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("production_runs") as batch:
            batch.alter_column("line_id", existing_type=sa.Integer(), nullable=False)
            batch.drop_column("line_slot")
        with op.batch_alter_table("production_capabilities") as batch:
            batch.alter_column("line_id", existing_type=sa.Integer(), nullable=False)
    else:
        op.alter_column(
            "production_runs",
            "line_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
        op.drop_column("production_runs", "line_slot")
        op.alter_column(
            "production_capabilities",
            "line_id",
            existing_type=sa.Integer(),
            nullable=False,
        )
    op.drop_table("production_settings")
