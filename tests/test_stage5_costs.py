"""Stage 5 专项测试：成本与基础财务一致性。"""
from datetime import date, datetime
from pathlib import Path
import sys

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import (
    _ship_order,
    allocate_payment,
    complete_production_run,
    create_payment,
    reverse_stock_transaction,
    send_external_processing,
    update_production_run_status,
)
from app.models import (
    ExternalProcessingBatch,
    InventoryItem,
    ProductBomItem,
    ProductionRun,
    ProductionSetting,
    Receivable,
    SalesOrder,
    SalesOrderItem,
    StockTransaction,
    StockTransactionItem,
)
from app.schemas import (
    ExternalProcessingSendPayload,
    PaymentAllocationPayload,
    PaymentPayload,
    ProductionCompletionPayload,
    ProductionRunStatusPayload,
)
from app.services import create_transaction, rebalance_product_reservations


NOW = datetime(2026, 8, 22, 8, 0)


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_part(db, sku="X", stock=0, cost=0.0):
    part = InventoryItem(sku=sku, name=sku, kind="PART", stock_qty=stock, cost_price=cost)
    db.add(part)
    db.flush()
    return part


def make_product(db, sku="P01", capacity=100):
    product = InventoryItem(
        sku=sku, name=sku, kind="PRODUCT", stock_qty=0,
        daily_capacity=capacity, mold_count=1, cost_price=0,
    )
    db.add(product)
    db.flush()
    return product


def make_bom(db, product, part, quantity=1):
    db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=quantity))
    db.flush()


def make_run(db, product, quantity):
    from app.models import ProductionMaterialReservation
    db.add(ProductionSetting(id=1, line_count=1))
    db.flush()
    run = ProductionRun(
        run_no="PR-TEST", product_id=product.id,
        planned_quantity=quantity, produced_quantity=0,
        planned_start_at=NOW, planned_end_at=NOW,
        effective_daily_capacity=product.daily_capacity,
        status="PLANNED", workflow_version=2, line_slot=1, mold_slot=1,
        schedule_locked=True,
    )
    db.add(run)
    db.flush()
    # 开工检查要求 reserved >= required，直接挂 ACTIVE 预留
    for component in product.bom_components:
        db.add(ProductionMaterialReservation(
            production_run_id=run.id,
            part_id=component.part_id,
            quantity=float(component.quantity) * quantity,
            status="ACTIVE",
        ))
    db.flush()
    return run


def start_run(db, run):
    return update_production_run_status(
        run.id, ProductionRunStatusPayload(status="RUNNING"), db,
    )


def complete_run(db, run, qualified, scrap=0, completion_date=date(2026, 8, 25)):
    return complete_production_run(
        run.id,
        ProductionCompletionPayload(
            qualified_quantity=qualified, scrap_quantity=scrap,
            completion_date=completion_date,
        ),
        db,
    )


def inbound(db, item, quantity, unit_cost):
    create_transaction(db, "PURCHASE_IN", [(item, quantity, unit_cost)], "采购入库")
    db.commit()


# ───────────────── 5A：生产成本使用领料快照 ─────────────────

def test_issue_snapshot_and_completion_cost():
    """领料按当时移动平均快照；完工成本 = 净领料价值 / 合格数量。"""
    with database() as db:
        part = make_part(db, "X", stock=1000, cost=5)
        product = make_product(db)
        make_bom(db, product, part, quantity=1)
        run = make_run(db, product, 100)
        start_run(db, run)
        db.expire_all()
        out_lines = db.scalars(
            select(StockTransactionItem)
            .join(StockTransaction, StockTransaction.id == StockTransactionItem.transaction_id)
            .where(StockTransaction.transaction_type == "PRODUCTION_OUT")
        ).all()
        # 领料快照 = 开工时点成本 5
        assert all(float(line.unit_cost) == 5 for line in out_lines)
        result = complete_run(db, run, qualified=100)
        assert result["net_material_cost"] == 500
        assert result["finished_unit_cost"] == 5


def test_price_rise_after_issue_does_not_change_old_run_cost():
    """开工后原料涨价（移动平均上升），旧批次成本不变。"""
    with database() as db:
        part = make_part(db, "X", stock=2000, cost=5)
        product = make_product(db)
        make_bom(db, product, part, quantity=1)
        run = make_run(db, product, 100)
        start_run(db, run)  # 领走 100@5，库存剩 1900@5
        # 开工后涨价：再采购 1000 @8 → 平均 (1900×5+8000)/2900 ≈ 6.03
        inbound(db, part, 1000, 8)
        db.refresh(part)
        assert float(part.cost_price) == round(17500 / 2900, 2)
        result = complete_run(db, run, qualified=100)
        # 成本仍按领料时点 5，不用完工时点均价
        assert result["net_material_cost"] == 500
        assert result["finished_unit_cost"] == 5


def test_scrap_cost_absorbed_by_qualified():
    """领料1000套@5、合格900、报废100 → 5000/900 摊到合格品。"""
    with database() as db:
        part = make_part(db, "X", stock=1000, cost=5)
        product = make_product(db)
        make_bom(db, product, part, quantity=1)
        run = make_run(db, product, 1000)
        start_run(db, run)
        result = complete_run(db, run, qualified=900, scrap=100)
        assert result["net_material_cost"] == 5000
        assert result["finished_unit_cost"] == round(5000 / 900, 2)


def test_underproduction_return_deducts_material_cost():
    """计划100、合格80 → 退料20套按领料快照计价，净成本 = 80套价值。"""
    with database() as db:
        part = make_part(db, "X", stock=1000, cost=5)
        product = make_product(db)
        make_bom(db, product, part, quantity=1)
        run = make_run(db, product, 100)
        start_run(db, run)
        result = complete_run(db, run, qualified=80)
        assert result["net_material_cost"] == 400
        assert result["finished_unit_cost"] == 5
        # 退料流水带领料时点快照成本
        return_line = db.scalar(
            select(StockTransactionItem)
            .join(StockTransaction, StockTransaction.id == StockTransactionItem.transaction_id)
            .where(StockTransaction.transaction_type == "PRODUCTION_RETURN")
        )
        assert float(return_line.unit_cost) == 5
        # 退料回库按快照价值，不污染零件均价
        db.refresh(part)
        assert float(part.stock_qty) == 920


def test_overproduction_extra_issue_counts_into_cost():
    """计划100、合格120 → 补领20套计入净成本 = 120套价值。"""
    with database() as db:
        part = make_part(db, "X", stock=2000, cost=5)
        product = make_product(db)
        make_bom(db, product, part, quantity=1)
        run = make_run(db, product, 100)
        start_run(db, run)
        result = complete_run(db, run, qualified=120)
        assert result["net_material_cost"] == 600
        assert result["finished_unit_cost"] == 5


def test_external_return_cost_adds_processing_fee():
    """外协回厂成本 = 半成品材料成本 + 本批次加工费按比例分摊。"""
    with database() as db:
        part = make_part(db, "X", stock=100, cost=5)
        product = make_product(db)
        product.requires_external_processing = True
        product.external_process_name = "喷漆"
        db.flush()
        make_bom(db, product, part, quantity=1)
        run = make_run(db, product, 50)
        start_run(db, run)
        complete_run(db, run, qualified=50)  # 半成品 50，单位材料成本 5
        db.refresh(product)
        assert int(product.semi_finished_qty) == 50

        batch = send_external_processing(
            ExternalProcessingSendPayload(
                product_id=product.id, quantity=50,
                supplier="加工商", processing_cost=100,
            ),
            db,
        )
        assert batch["processing_cost"] == 100
        from app.main import return_external_processing
        from app.schemas import ExternalProcessingReturnPayload
        result = return_external_processing(
            batch["id"],
            ExternalProcessingReturnPayload(quantity=25),
            db,
        )
        tx = db.get(StockTransaction, result["transaction_id"])
        # 5 材料成本 + 100/50 加工费分摊 = 7
        assert float(tx.lines[0].unit_cost) == 7


# ───────────────── 5B：移动平均与冲销 ─────────────────

def test_purchase_reversal_restores_cost():
    """10@5 + 10@8 → 20@6.5；冲销 @8 那笔 → 库存与成本都回到 10@5。"""
    with database() as db:
        part = make_part(db, "X")
        first = create_transaction(db, "PURCHASE_IN", [(part, 10, 5)], "第一批")
        second = create_transaction(db, "PURCHASE_IN", [(part, 10, 8)], "第二批")
        db.commit()
        assert float(part.stock_qty) == 20
        assert float(part.cost_price) == 6.5

        reverse_stock_transaction(second.id, db)
        db.refresh(part)
        assert float(part.stock_qty) == 10
        assert float(part.cost_price) == 5
        # 第一批流水不受影响
        db.refresh(first)
        assert first.status == "POSTED"


def test_purchase_reversal_rejected_when_consumed():
    """10@5 + 10@8 后已出库 15：再冲销 10 的采购被拒绝。"""
    with database() as db:
        part = make_part(db, "X")
        create_transaction(db, "PURCHASE_IN", [(part, 10, 5)], "第一批")
        second = create_transaction(db, "PURCHASE_IN", [(part, 10, 8)], "第二批")
        create_transaction(db, "MANUAL_OUT", [(part, -15, part.cost_price)], "消耗")
        db.commit()
        assert float(part.stock_qty) == 5
        try:
            reverse_stock_transaction(second.id, db)
            raise AssertionError("已消耗的采购入库应当拒绝冲销")
        except HTTPException as error:
            assert error.status_code == 409
            assert "不能直接冲销" in error.detail
        db.refresh(part)
        assert float(part.stock_qty) == 5


def test_purchase_reversal_allowed_when_stock_replenished():
    """库存回补到足够覆盖原入库数量后，允许冲销。"""
    with database() as db:
        part = make_part(db, "X")
        create_transaction(db, "PURCHASE_IN", [(part, 10, 5)], "第一批")
        second = create_transaction(db, "PURCHASE_IN", [(part, 10, 8)], "第二批")
        create_transaction(db, "MANUAL_OUT", [(part, -15, part.cost_price)], "消耗")
        create_transaction(db, "GENERAL_IN", [(part, 10, 4)], "回补")
        db.commit()
        assert float(part.stock_qty) == 15
        reverse_stock_transaction(second.id, db)
        db.refresh(part)
        assert float(part.stock_qty) == 5
        # 已知近似（交接 5B 允许）：此前按均价 6.5 出货，冲销 @8 批次会把隐含
        # 账面价值打到负数；不做 COGS 重放，价值下限 clamp 到 0。
        # 关键断言：数量正确、成本落在合理区间、不抛异常。
        assert 0 <= float(part.cost_price) < 100
