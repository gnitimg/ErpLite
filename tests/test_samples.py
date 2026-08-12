from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import samples, update_sample
from app.models import Base, InventoryItem, StockTransaction
from app.schemas import SamplePayload


def test_sample_inventory_follows_all_active_products_including_zero_stock():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = InventoryItem(
            sku="PRODUCT-01",
            name="演示产品一",
            kind="PRODUCT",
            sample_stock_qty=0,
        )
        second = InventoryItem(
            sku="PRODUCT-02",
            name="演示产品二",
            kind="PRODUCT",
            sample_stock_qty=25,
        )
        part = InventoryItem(sku="PART-01", name="普通零件", kind="PART")
        db.add_all([first, second, part])
        db.commit()

        rows = samples(db=db)
        assert [row["sku"] for row in rows] == ["PRODUCT-01", "PRODUCT-02"]
        assert [row["sample_stock_qty"] for row in rows] == [0, 25]

        updated = update_sample(first.id, SamplePayload(stock_qty=12), db)
        assert updated["sample_stock_qty"] == 12
        assert db.get(InventoryItem, first.id).stock_qty == 0
        transaction = db.query(StockTransaction).one()
        assert transaction.transaction_type == "SAMPLE_ADJUST"
        assert transaction.lines[0].quantity_change == 12

        filtered = samples(keyword="产品二", db=db)
        assert [row["sku"] for row in filtered] == ["PRODUCT-02"]
