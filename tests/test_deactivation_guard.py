"""停用守卫与对账并发安全测试。"""
from datetime import datetime, date
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import (
    delete_part, delete_product, reconcile_stock, audit_primary_stock,
    update_sample, create_purchase_commitment, create_manual_production_run,
    save_product,
)
from app.models import (
    ExternalProcessingBatch,
    InventoryItem,
    ProductionRun,
    PurchaseCommitment,
    StockTransaction,
    StockTransactionItem,
)
from app.schemas import (
    StockReconciliationPayload,
    SamplePayload,
    PurchaseCommitmentPayload,
    ManualProductionRunPayload,
    ProductPayload,
    BomLinePayload,
)
from app.services import create_transaction


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_part(db, sku="X", stock=0):
    part = InventoryItem(sku=sku, name=sku, kind="PART", stock_qty=stock, cost_price=0)
    db.add(part)
    db.flush()
    return part


def make_product(db, sku="P01", stock=0):
    product = InventoryItem(
        sku=sku, name=sku, kind="PRODUCT", stock_qty=stock,
        daily_capacity=100, mold_count=1, cost_price=0,
    )
    db.add(product)
    db.flush()
    return product


# ───────────────── PART 停用守卫 ─────────────────

def test_part_deactivate_with_stock_blocked():
    with database() as db:
        part = make_part(db, "X", stock=100)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_part(part.id, db)
        assert exc.value.status_code == 409
        assert "库存" in exc.value.detail


def test_part_deactivate_with_planned_commitment_blocked():
    with database() as db:
        part = make_part(db, "X", stock=0)
        db.add(PurchaseCommitment(
            part_id=part.id, quantity=50, expected_arrival_at=datetime(2026, 9, 1),
            status="PLANNED",
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_part(part.id, db)
        assert exc.value.status_code == 409
        assert "采购" in exc.value.detail


def test_part_deactivate_zero_stock_no_commit_ok():
    with database() as db:
        part = make_part(db, "X", stock=0)
        db.commit()
        result = delete_part(part.id, db)
        assert result["ok"] is True
        assert part.active is False


# ───────────────── PRODUCT 停用守卫 ─────────────────

def test_product_deactivate_with_stock_blocked():
    with database() as db:
        product = make_product(db, "P01", stock=50)
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_product(product.id, db)
        assert exc.value.status_code == 409
        assert "库存" in exc.value.detail


def test_product_deactivate_with_semi_finished_blocked():
    with database() as db:
        product = make_product(db, "P01", stock=0)
        product.semi_finished_qty = 20
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_product(product.id, db)
        assert exc.value.status_code == 409
        assert "半成品" in exc.value.detail


def test_product_deactivate_with_processing_qty_blocked():
    with database() as db:
        product = make_product(db, "P01", stock=0)
        product.processing_qty = 5
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_product(product.id, db)
        assert exc.value.status_code == 409
        assert "外协" in exc.value.detail


def test_product_deactivate_with_active_run_blocked():
    with database() as db:
        product = make_product(db, "P01", stock=0)
        product.sample_stock_qty = 0
        db.add(ProductionRun(
            run_no="PR-1", product_id=product.id,
            planned_quantity=100, produced_quantity=0,
            planned_start_at=datetime(2026, 8, 22),
            planned_end_at=datetime(2026, 8, 25),
            effective_daily_capacity=100,
            status="PLANNED", workflow_version=2, line_slot=1, mold_slot=1,
            schedule_locked=True,
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_product(product.id, db)
        assert exc.value.status_code == 409
        assert "生产" in exc.value.detail


def test_product_deactivate_with_sent_batch_blocked():
    with database() as db:
        product = make_product(db, "P01", stock=10)
        product.sample_stock_qty = 0
        tx = create_transaction(db, "MANUAL_OUT", [(product, -10, 5)], "外协发出")
        db.flush()
        product.processing_qty = 0
        product.stock_qty = 0
        db.flush()
        db.add(ExternalProcessingBatch(
            batch_no="EP-1", product_id=product.id,
            process_name_snapshot="电镀", quantity=10,
            status="SENT", outbound_transaction_id=tx.id,
            sent_at=datetime(2026, 8, 22),
        ))
        db.commit()
        with pytest.raises(HTTPException) as exc:
            delete_product(product.id, db)
        assert exc.value.status_code == 409
        assert "外协" in exc.value.detail


def test_product_deactivate_all_zero_ok():
    with database() as db:
        product = make_product(db, "P01", stock=0)
        product.semi_finished_qty = 0
        product.processing_qty = 0
        product.sample_stock_qty = 0
        db.commit()
        result = delete_product(product.id, db)
        assert result["ok"] is True
        assert product.active is False


# ───────────────── 盘点拒绝停用物料 ─────────────────

def test_stocktake_inactive_item_rejected():
    """停用物料不能参与盘点，防止主动制造幽灵库存。"""
    with database() as db:
        part = make_part(db, "X", stock=100)
        part.active = False
        db.commit()
        with pytest.raises(HTTPException) as exc:
            reconcile_stock(
                StockReconciliationPayload(
                    items=[{"item_id": part.id, "physical_count": 90}],
                    notes="测试停用物料盘点",
                ),
                db,
            )
        assert exc.value.status_code == 409
        assert "停用" in exc.value.detail


# ───────────────── audit 覆盖停用物料 ─────────────────

def test_audit_returns_inactive_item():
    """系统库存对账必须返回停用物料，用于发现历史幽灵库存。"""
    with database() as db:
        part = make_part(db, "X", stock=100)
        part.active = False
        db.commit()
        result = audit_primary_stock(db)
        matching = [row for row in result if row["item_id"] == part.id]
        assert len(matching) == 1
        assert matching[0]["active"] is False
        assert matching[0]["stored_stock"] == 100.0


# ───────────────── create_transaction 拒绝停用物料 ─────────────────

def test_create_transaction_rejects_inactive_item():
    """停用物料的库存操作必须被拒绝，防止并发竞态产生幽灵库存。"""
    with database() as db:
        part = make_part(db, "X", stock=0)
        part.active = False
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_transaction(db, "MANUAL_IN", [(part, 10, 5)], "测试停用物料入库")
        assert exc.value.status_code == 409
        assert "停用" in exc.value.detail


# ───────────────── 写端统一锁：停用物料拒绝操作 ─────────────────

def test_update_sample_rejects_inactive_product():
    """停用产品的样品库存不能修改。"""
    with database() as db:
        product = make_product(db, "P01", stock=0)
        product.sample_stock_qty = 0
        product.active = False
        db.commit()
        with pytest.raises(HTTPException) as exc:
            update_sample(product.id, SamplePayload(stock_qty=10), db)
        assert exc.value.status_code == 404


def test_create_purchase_commitment_rejects_inactive_part():
    """停用零件不能创建采购预计。"""
    with database() as db:
        part = make_part(db, "X", stock=0)
        part.active = False
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_purchase_commitment(
                PurchaseCommitmentPayload(
                    part_id=part.id, quantity=50,
                    expected_arrival_date=date(2026, 9, 1),
                ),
                db,
            )
        assert exc.value.status_code == 404


def test_create_manual_production_run_rejects_inactive_product():
    """停用产品不能创建手工生产计划。"""
    with database() as db:
        product = make_product(db, "P01", stock=0)
        product.sample_stock_qty = 0
        product.active = False
        db.commit()
        with pytest.raises(HTTPException) as exc:
            create_manual_production_run(
                ManualProductionRunPayload(
                    product_id=product.id, planned_quantity=100,
                ),
                db,
            )
        assert exc.value.status_code == 404


def test_save_product_rejects_inactive_bom_part():
    """BOM 中包含停用零件时不能保存产品。"""
    with database() as db:
        part = make_part(db, "X", stock=0)
        part.active = False
        product = make_product(db, "P01", stock=0)
        product.sample_stock_qty = 0
        db.commit()
        with pytest.raises(HTTPException) as exc:
            save_product(
                db,
                ProductPayload(
                    sku="P01", name="P01", daily_capacity=100,
                    components=[BomLinePayload(part_id=part.id, quantity=1)],
                ),
                product,
            )
        assert exc.value.status_code == 400
