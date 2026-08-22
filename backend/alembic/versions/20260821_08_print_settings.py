"""global document print size settings

Revision ID: 20260821_08
Revises: 20260821_07
"""

from alembic import op
import sqlalchemy as sa


revision = "20260821_08"
down_revision = "20260821_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "production_settings",
        sa.Column(
            "print_paper_preset",
            sa.String(30),
            nullable=False,
            server_default="A4_LANDSCAPE",
        ),
    )
    op.add_column(
        "production_settings",
        sa.Column("print_width_mm", sa.Float(), nullable=False, server_default="297"),
    )
    op.add_column(
        "production_settings",
        sa.Column("print_height_mm", sa.Float(), nullable=False, server_default="210"),
    )


def downgrade() -> None:
    op.drop_column("production_settings", "print_height_mm")
    op.drop_column("production_settings", "print_width_mm")
    op.drop_column("production_settings", "print_paper_preset")
