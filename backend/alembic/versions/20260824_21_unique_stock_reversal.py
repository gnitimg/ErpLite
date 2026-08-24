"""serialize stock transaction reversal at the database boundary

Revision ID: 20260824_21
Revises: 20260822_20
"""

from alembic import op
import sqlalchemy as sa


revision = "20260824_21"
down_revision = "20260822_20"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "uq_stock_transactions_reversal_of"
COLUMNS = ["reversal_of_transaction_id"]


def _has_unique_constraint(bind) -> bool:
    inspector = sa.inspect(bind)
    constraints = inspector.get_unique_constraints("stock_transactions")
    indexes = inspector.get_indexes("stock_transactions")
    return any(
        constraint.get("name") == CONSTRAINT_NAME
        or constraint.get("column_names") == COLUMNS
        for constraint in constraints
    ) or any(
        index.get("unique") and index.get("column_names") == COLUMNS
        for index in indexes
    )


def upgrade() -> None:
    bind = op.get_bind()
    if _has_unique_constraint(bind):
        return

    duplicate = bind.execute(
        sa.text(
            "SELECT reversal_of_transaction_id, COUNT(*) AS duplicate_count "
            "FROM stock_transactions "
            "WHERE reversal_of_transaction_id IS NOT NULL "
            "GROUP BY reversal_of_transaction_id HAVING COUNT(*) > 1 LIMIT 1"
        )
    ).first()
    if duplicate:
        raise RuntimeError(
            "Cannot add uq_stock_transactions_reversal_of: historical duplicate "
            f"reversals exist for transaction {duplicate[0]} (count={duplicate[1]}). "
            "Resolve the duplicate business records manually before retrying the migration."
        )

    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("stock_transactions") as batch_op:
            batch_op.create_unique_constraint(CONSTRAINT_NAME, COLUMNS)
    else:
        op.create_unique_constraint(CONSTRAINT_NAME, "stock_transactions", COLUMNS)


def downgrade() -> None:
    bind = op.get_bind()
    if not _has_unique_constraint(bind):
        return
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("stock_transactions") as batch_op:
            batch_op.drop_constraint(CONSTRAINT_NAME, type_="unique")
    else:
        op.drop_constraint(CONSTRAINT_NAME, "stock_transactions", type_="unique")
