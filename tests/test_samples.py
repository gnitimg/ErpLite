from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import create_sample, update_sample
from app.models import Base, InventoryItem, StockTransaction
from app.schemas import SamplePayload


def test_sample_defaults_and_stock_adjustments_are_traced():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        created = create_sample(SamplePayload(sku="sample-01", name="演示样品"), db)
        assert created["sku"] == "SAMPLE-01"
        assert created["stock_qty"] == 300

        updated = update_sample(
            created["id"],
            SamplePayload(
                sku="sample-01",
                name="演示样品",
                stock_qty=280,
            ),
            db,
        )
        assert updated["stock_qty"] == 280
        assert db.scalar(select(InventoryItem.stock_qty)) == 280

        transactions = db.scalars(
            select(StockTransaction).order_by(StockTransaction.id)
        ).all()
        assert [transaction.transaction_type for transaction in transactions] == [
            "SAMPLE_ADJUST",
            "SAMPLE_ADJUST",
        ]
        assert [transaction.lines[0].quantity_change for transaction in transactions] == [
            300,
            -20,
        ]
