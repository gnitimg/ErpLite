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


def _column(bind, table_name: str, column_name: str) -> dict:
    return next(
        column
        for column in sa.inspect(bind).get_columns(table_name)
        if column["name"] == column_name
    )


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
    if bind.execute(sa.text(
        "SELECT 1 FROM production_settings WHERE id = 1"
    )).first() is None:
        active_line_count = bind.execute(sa.text(
            "SELECT COUNT(*) FROM production_lines WHERE active = 1"
        )).scalar_one()
        values = {
            "id": 1,
            "line_count": max(int(active_line_count or 0), 1),
            "updated_at": sa.func.now(),
        }
        current_schema_defaults = {
            "schedule_auto_snap": True,
            "working_weekdays": "1,2,3,4,5",
            "print_paper_preset": "A4_LANDSCAPE",
            "print_width_mm": 297,
            "print_height_mm": 210,
        }
        values.update({
            name: value
            for name, value in current_schema_defaults.items()
            if name in setting_columns
        })
        settings_table = sa.Table(
            "production_settings", sa.MetaData(), autoload_with=bind
        )
        bind.execute(settings_table.insert().values(**values))

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

    capability_line = _column(bind, "production_capabilities", "line_id")
    run_line = _column(bind, "production_runs", "line_id")
    if bind.dialect.name == "sqlite" and (
        not capability_line["nullable"] or not run_line["nullable"]
    ):
        with op.batch_alter_table("production_capabilities") as batch:
            if not capability_line["nullable"]:
                batch.alter_column("line_id", existing_type=sa.Integer(), nullable=True)
        with op.batch_alter_table("production_runs") as batch:
            if not run_line["nullable"]:
                batch.alter_column("line_id", existing_type=sa.Integer(), nullable=True)
    else:
        if not capability_line["nullable"]:
            op.alter_column(
                "production_capabilities", "line_id",
                existing_type=capability_line["type"], nullable=True,
            )
        if not run_line["nullable"]:
            op.alter_column(
                "production_runs", "line_id",
                existing_type=run_line["type"], nullable=True,
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
