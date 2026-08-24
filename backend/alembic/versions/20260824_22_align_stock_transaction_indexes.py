"""align stock transaction reversal indexes with model metadata

Revision ID: 20260824_22
Revises: 20260824_21
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_22"
down_revision = "20260824_21"
branch_labels = None
depends_on = None


REDUNDANT_INDEX = "ix_stock_transactions_reversal_of"


def _index_names(bind) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(bind).get_indexes("stock_transactions")
    }


def upgrade() -> None:
    bind = op.get_bind()
    if REDUNDANT_INDEX in _index_names(bind):
        op.drop_index(REDUNDANT_INDEX, table_name="stock_transactions")


def downgrade() -> None:
    bind = op.get_bind()
    if REDUNDANT_INDEX not in _index_names(bind):
        op.create_index(
            REDUNDANT_INDEX,
            "stock_transactions",
            ["reversal_of_transaction_id"],
        )
