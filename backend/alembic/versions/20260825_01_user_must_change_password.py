"""add users.must_change_password flag for first-login forced password change

Revision ID: 20260825_01
Revises: 20260824_23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260825_01"
down_revision = "20260824_23"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {c["name"] for c in inspector.get_columns("users")}
    if "must_change_password" not in columns:
        op.add_column(
            "users",
            sa.Column("must_change_password", sa.Boolean(), nullable=False, server_default=sa.text("0")),
        )


def downgrade() -> None:
    op.drop_column("users", "must_change_password")
