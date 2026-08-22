"""add production run termination fields and material reservations

Revision ID: 20260822_11
Revises: 20260822_10
"""

from alembic import op
import sqlalchemy as sa


revision = "20260822_11"
down_revision = "20260822_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("production_runs")}
    if "scrap_quantity" not in columns:
        op.add_column(
            "production_runs",
            sa.Column("scrap_quantity", sa.Integer(), nullable=False, server_default="0"),
        )
    if "termination_reason" not in columns:
        op.add_column(
            "production_runs",
            sa.Column("termination_reason", sa.Text(), nullable=True),
        )
        op.execute(
            sa.text("UPDATE production_runs SET termination_reason = '' WHERE termination_reason IS NULL")
        )
        op.alter_column(
            "production_runs",
            "termination_reason",
            existing_type=sa.Text(),
            nullable=False,
        )
    if "terminated_at" not in columns:
        op.add_column(
            "production_runs",
            sa.Column("terminated_at", sa.DateTime(), nullable=True),
        )
    if "workflow_version" not in columns:
        op.add_column(
            "production_runs",
            sa.Column("workflow_version", sa.Integer(), nullable=False, server_default="1"),
        )

    table_names = set(inspector.get_table_names())
    if "production_material_reservations" not in table_names:
        op.create_table(
            "production_material_reservations",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column(
                "production_run_id",
                sa.Integer(),
                sa.ForeignKey("production_runs.id", ondelete="CASCADE"),
                nullable=False,
                index=True,
            ),
            sa.Column(
                "part_id",
                sa.Integer(),
                sa.ForeignKey("inventory_items.id", ondelete="RESTRICT"),
                nullable=False,
                index=True,
            ),
            sa.Column("quantity", sa.Float(), nullable=False, server_default="0"),
            sa.Column("status", sa.String(length=20), nullable=False, server_default="ACTIVE", index=True),
            sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
            sa.UniqueConstraint("production_run_id", "part_id", name="uq_run_part_reservation"),
        )
        op.create_index(
            "ix_reservation_part_status",
            "production_material_reservations",
            ["part_id", "status"],
        )


def downgrade() -> None:
    op.drop_table("production_material_reservations")
    op.drop_column("production_runs", "workflow_version")
    op.drop_column("production_runs", "terminated_at")
    op.drop_column("production_runs", "termination_reason")
    op.drop_column("production_runs", "scrap_quantity")
