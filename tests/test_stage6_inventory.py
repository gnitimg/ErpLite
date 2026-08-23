from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import audit_primary_stock, reverse_stock_transaction, stocktake
from app.models import InventoryItem, StockTransaction
from app.schemas import StocktakeLinePayload, StocktakePayload
from app.services import create_transaction


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def take(db: Session, *lines: tuple[InventoryItem, float]) -> dict:
    return stocktake(
        StocktakePayload(items=[
            StocktakeLinePayload(item_id=item.id, physical_count=physical)
            for item, physical in lines
        ]),
        db,
    )


def test_stocktake_decrease_creates_manual_out():
    with database() as db:
        part = InventoryItem(sku="PART-OUT", name="盘亏零件", kind="PART", stock_qty=100)
        db.add(part)
        db.flush()

        result = take(db, (part, 95))

        assert part.stock_qty == 95
        assert result["transactions"][0]["transaction_type"] == "MANUAL_OUT"
        tx = db.get(StockTransaction, result["transactions"][0]["id"])
        assert tx.lines[0].quantity_change == -5


def test_stocktake_increase_creates_manual_in():
    with database() as db:
        part = InventoryItem(sku="PART-IN", name="盘盈零件", kind="PART", stock_qty=100)
        db.add(part)
        db.flush()

        result = take(db, (part, 110))

        assert part.stock_qty == 110
        assert result["transactions"][0]["transaction_type"] == "MANUAL_IN"
        tx = db.get(StockTransaction, result["transactions"][0]["id"])
        assert tx.lines[0].quantity_change == 10


def test_mixed_stocktake_splits_inbound_and_outbound_transactions():
    with database() as db:
        gained = InventoryItem(sku="GAIN", name="盘盈", kind="PART", stock_qty=10)
        lost = InventoryItem(sku="LOSS", name="盘亏", kind="PART", stock_qty=10)
        db.add_all([gained, lost])
        db.flush()

        result = take(db, (gained, 20), (lost, 5))

        assert {row["transaction_type"] for row in result["transactions"]} == {"MANUAL_IN", "MANUAL_OUT"}
        assert gained.stock_qty == 20
        assert lost.stock_qty == 5


def test_stocktake_supports_part_and_product():
    with database() as db:
        part = InventoryItem(sku="PART", name="零件", kind="PART", stock_qty=10)
        product = InventoryItem(
            sku="PRODUCT",
            name="产品",
            kind="PRODUCT",
            stock_qty=10,
            daily_capacity=1,
            mold_count=1,
        )
        db.add_all([part, product])
        db.flush()

        result = take(db, (part, 11), (product, 9))

        assert result["discrepancy_count"] == 2
        assert part.stock_qty == 11
        assert product.stock_qty == 9


def test_audit_historical_sum_handles_purchase_sale_and_reversal_once():
    with database() as db:
        part = InventoryItem(sku="AUDIT", name="审计零件", kind="PART", stock_qty=0)
        db.add(part)
        db.flush()
        create_transaction(db, "OPENING", [(part, 100, 5)], "期初")
        sale = create_transaction(db, "MANUAL_OUT", [(part, -20, 5)], "领用")
        db.commit()
        reverse_stock_transaction(sale.id, db)

        result = audit_primary_stock(db)

        assert len(result) == 1
        assert result[0]["stored_stock"] == 100
        assert result[0]["ledger_stock"] == 100
        assert result[0]["difference"] == 0
        assert result[0]["ok"] is True
        statuses = db.execute(select(StockTransaction.transaction_type, StockTransaction.status)).all()
        assert ("MANUAL_OUT", "REVERSED") in statuses
        assert ("REVERSAL", "POSTED") in statuses


def test_audit_detects_direct_stock_tampering_and_is_read_only():
    with database() as db:
        part = InventoryItem(sku="TAMPER", name="篡改检测", kind="PART", stock_qty=0)
        db.add(part)
        db.flush()
        create_transaction(db, "OPENING", [(part, 100, 5)], "期初")
        db.commit()
        part.stock_qty += 1
        db.commit()

        result = audit_primary_stock(db)

        assert result[0]["stored_stock"] == 101
        assert result[0]["ledger_stock"] == 100
        assert result[0]["difference"] == 1
        assert result[0]["ok"] is False
        db.refresh(part)
        assert part.stock_qty == 101


def test_audit_uses_current_stock_as_baseline_without_history():
    with database() as db:
        part = InventoryItem(sku="LEGACY", name="无流水旧库存", kind="PART", stock_qty=12)
        db.add(part)
        db.commit()

        result = audit_primary_stock(db)

        assert result[0]["ledger_stock"] == 12
        assert result[0]["ok"] is True
        assert result[0]["audit_note"] == "无历史流水，使用当前库存作为基准"
