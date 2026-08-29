"""add print brand header settings (mode/company name/logo)

Revision ID: 20260829_01
Revises: 20260825_02
"""

import sqlalchemy as sa
from alembic import op


revision = "20260829_01"
down_revision = "20260825_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    columns = {column["name"] for column in sa.inspect(bind).get_columns("production_settings")}
    if "print_header_mode" not in columns:
        op.add_column(
            "production_settings",
            sa.Column("print_header_mode", sa.String(length=10), nullable=False, server_default="none"),
        )
    if "print_company_name" not in columns:
        op.add_column(
            "production_settings",
            sa.Column("print_company_name", sa.String(length=100), nullable=False, server_default=""),
        )
    if "print_logo" not in columns:
        op.add_column(
            "production_settings",
            sa.Column("print_logo", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_column("production_settings", "print_logo")
    op.drop_column("production_settings", "print_company_name")
    op.drop_column("production_settings", "print_header_mode")
