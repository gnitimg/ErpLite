"""drop legacy auto-named stock transaction reversal indexes

Revision ID: 20260824_23
Revises: 20260824_22
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_23"
down_revision = "20260824_22"
branch_labels = None
depends_on = None


LEGACY_INDEXES = {
    "ix_stock_transactions_reversal_of_transaction_id": "reversal_of_transaction_id",
    "ix_stock_transactions_reversed_by_transaction_id": "reversed_by_transaction_id",
}


def _index_names(bind) -> set[str]:
    return {
        index["name"]
        for index in sa.inspect(bind).get_indexes("stock_transactions")
    }


def upgrade() -> None:
    existing = _index_names(op.get_bind())
    for name in LEGACY_INDEXES:
        if name in existing:
            op.drop_index(name, table_name="stock_transactions")


def downgrade() -> None:
    existing = _index_names(op.get_bind())
    for name, column in LEGACY_INDEXES.items():
        if name not in existing:
            op.create_index(name, "stock_transactions", [column])

