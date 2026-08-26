"""add document numbering rules and personal navigation settings

Revision ID: 20260825_02
Revises: 20260825_01
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "20260825_02"
down_revision = "20260825_01"
branch_labels = None
depends_on = None


DEFAULT_RULES = (
    ("SO", "SO"),
    ("ST", "ST"),
    ("PR", "PR"),
    ("EP", "EP"),
    ("RT", "RT"),
    ("AR", "AR"),
    ("PAY", "PAY"),
    ("CR", "CR"),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "document_number_rules" not in tables:
        op.create_table(
            "document_number_rules",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("document_type", sa.String(length=20), nullable=False),
            sa.Column("prefix", sa.String(length=12), nullable=False, server_default=""),
            sa.Column("next_number", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("digits", sa.Integer(), nullable=False, server_default="6"),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
        )
        op.create_index(
            "ix_document_number_rules_document_type",
            "document_number_rules",
            ["document_type"],
            unique=True,
        )
        rules = sa.table(
            "document_number_rules",
            sa.column("document_type", sa.String),
            sa.column("prefix", sa.String),
            sa.column("next_number", sa.Integer),
            sa.column("digits", sa.Integer),
            sa.column("updated_at", sa.DateTime),
        )
        op.bulk_insert(rules, [
            {
                "document_type": document_type,
                "prefix": prefix,
                "next_number": 1,
                "digits": 6,
                "updated_at": datetime.now(),
            }
            for document_type, prefix in DEFAULT_RULES
        ])
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "navigation_config" not in user_columns:
        op.add_column(
            "users",
            sa.Column(
                "navigation_config",
                sa.String(length=4000),
                nullable=False,
                server_default="",
            ),
        )


def downgrade() -> None:
    op.drop_column("users", "navigation_config")
    op.drop_index(
        "ix_document_number_rules_document_type",
        table_name="document_number_rules",
    )
    op.drop_table("document_number_rules")
