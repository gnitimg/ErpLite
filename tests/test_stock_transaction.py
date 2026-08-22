from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import InventoryItem, StockTransactionItem
from app.services import create_transaction


def test_compound_transaction_updates_balance_and_ledger_together():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        part = InventoryItem(sku="PART-01", name="零件", kind="PART", stock_qty=0)
        product = InventoryItem(sku="PRODUCT-01", name="产品", kind="PRODUCT", stock_qty=0)
        db.add_all([part, product])
        db.commit()

        create_transaction(db, "OPENING", [(part, 10, 2)], "期初盘点")
        db.commit()

        transaction = create_transaction(
            db,
            "ASSEMBLY_IN",
            [(part, -4, 2), (product, 1, 12)],
            "测试生产",
        )
        db.commit()

        assert transaction.lines[0].item_id == part.id
        assert len(transaction.lines) == 2
        assert db.get(InventoryItem, part.id).stock_qty == 6
        assert db.get(InventoryItem, product.id).stock_qty == 1
        for item in (part, product):
            ledger_qty = db.scalar(
                select(func.sum(StockTransactionItem.quantity_change))
                .where(StockTransactionItem.item_id == item.id)
            )
            assert item.stock_qty == ledger_qty


def test_compound_transaction_rejects_shortage_without_partial_changes():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        part = InventoryItem(sku="PART-01", name="零件", kind="PART", stock_qty=1)
        product = InventoryItem(sku="PRODUCT-01", name="产品", kind="PRODUCT", stock_qty=0)
        db.add_all([part, product])
        db.commit()

        with pytest.raises(HTTPException) as error:
            create_transaction(db, "ASSEMBLY_IN", [(part, -2, 2), (product, 1, 12)])
        db.rollback()

        assert error.value.status_code == 409
        assert db.get(InventoryItem, part.id).stock_qty == 1
        assert db.get(InventoryItem, product.id).stock_qty == 0
        assert db.scalar(select(func.count()).select_from(StockTransactionItem)) == 0


def test_transaction_rejects_changes_that_cancel_each_other():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        item = InventoryItem(sku="PART-01", name="零件", kind="PART", stock_qty=1)
        db.add(item)
        db.commit()

        with pytest.raises(HTTPException) as error:
            create_transaction(db, "MANUAL_IN", [(item, 1, 0), (item, -1, 0)])

        assert error.value.status_code == 400
