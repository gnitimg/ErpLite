"""Stage 4 专项测试：统一未来供给 / 生产日历 / 物料时间轴 / ETA 时间模型。"""
from datetime import date, datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import cancel_order
from app.models import (
    InventoryItem,
    ProductionAllocation,
    ProductionRun,
    ProductionSetting,
    SalesOrder,
    SalesOrderItem,
)
from app.planning import recalculate_production_plan
from app.schemas import OrderCancelPayload


NOW = datetime(2026, 8, 20, 8, 0, 0)


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_product(db: Session, sku: str, daily_capacity: int = 1000) -> InventoryItem:
    product = InventoryItem(
        sku=sku, name=sku, kind="PRODUCT", stock_qty=0,
        daily_capacity=daily_capacity, mold_count=1,
    )
    db.add(product)
    db.flush()
    return product


def add_order(
    db: Session,
    order_no: str,
    requirements: list[tuple[InventoryItem, int]],
    days_until_due: int = 5,
) -> SalesOrder:
    order = SalesOrder(
        order_no=order_no,
        customer_name=order_no,
        status="CONFIRMED",
        order_date=date(2026, 8, 20),
        required_date=date(2026, 8, 20) + timedelta(days=days_until_due),
        total_amount=0,
    )
    order.items = [
        SalesOrderItem(
            product_id=product.id,
            quantity=quantity,
            reference_price=1,
            unit_price=1,
            line_total=quantity,
        )
        for product, quantity in requirements
    ]
    db.add(order)
    db.flush()
    return order


def add_setting(db: Session, line_count: int = 1) -> None:
    db.add(ProductionSetting(id=1, line_count=line_count))
    db.flush()


def add_running_run(
    db: Session,
    product: InventoryItem,
    quantity: int,
    line_slot: int = 1,
) -> ProductionRun:
    run = ProductionRun(
        run_no=f"RUN-{product.sku}-{quantity}",
        product_id=product.id,
        planned_quantity=quantity,
        planned_start_at=NOW,
        planned_end_at=NOW + timedelta(days=quantity / max(float(product.daily_capacity), 1)),
        status="RUNNING",
        source_type="ORDER",
        line_slot=line_slot,
        mold_slot=1,
        effective_daily_capacity=product.daily_capacity,
        workflow_version=2,
    )
    db.add(run)
    db.flush()
    return run


def allocate(
    db: Session, run: ProductionRun, order: SalesOrder, quantity: int, sequence: int = 1
) -> ProductionAllocation:
    allocation = ProductionAllocation(
        production_run_id=run.id,
        order_item_id=order.items[0].id,
        quantity=quantity,
        sequence=sequence,
        estimated_completion_at=run.planned_end_at,
    )
    db.add(allocation)
    db.flush()
    return allocation


def all_runs(db: Session) -> list[ProductionRun]:
    return db.scalars(select(ProductionRun)).all()


# ───────────────── 4B：统一 Fixed Run Future Supply ─────────────────

def test_locked_order_run_free_supply_covers_new_demand():
    """CASE 1：锁定 ORDER run 1000（A600+B400），A 取消 keep_runs → 新需求 600 复用空余，不建新批次。"""
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01")
        order_a = add_order(db, "SO-A", [(product, 600)], days_until_due=3)
        order_b = add_order(db, "SO-B", [(product, 400)], days_until_due=5)
        recalculate_production_plan(db, NOW)
        assert len(all_runs(db)) == 1
        all_runs(db)[0].schedule_locked = True
        db.flush()

        cancel_order(order_a.id, OrderCancelPayload(disposition="keep_runs"), db)
        db.expire_all()
        kept = all_runs(db)[0]
        assert int(kept.planned_quantity) == 1000
        assert sum(int(a.quantity) for a in kept.allocations) == 400

        order_c = add_order(db, "SO-C", [(product, 600)], days_until_due=7)
        recalculate_production_plan(db, NOW)
        db.expire_all()
        runs = all_runs(db)
        assert len(runs) == 1, "空余 600 必须复用固定批次，不得新建 ProductionRun"
        assert sorted(int(a.quantity) for a in runs[0].allocations) == [400, 600]
        db.refresh(order_c.items[0])
        assert order_c.items[0].estimated_completion_at == runs[0].planned_end_at


def test_running_run_free_supply_covers_new_demand():
    """CASE 2：RUNNING run 1000 已分配 700 → 新需求 300 全部来自剩余产能。"""
    with database() as db:
        add_setting(db, line_count=2)
        product = make_product(db, "P01")
        order_a = add_order(db, "SO-A", [(product, 700)])
        run = add_running_run(db, product, 1000)
        allocate(db, run, order_a, 700)
        order_b = add_order(db, "SO-B", [(product, 300)], days_until_due=6)

        recalculate_production_plan(db, NOW)
        db.expire_all()
        assert len(all_runs(db)) == 1, "RUNNING 剩余 300 足以覆盖新需求，不得新建批次"
        db.refresh(order_b.items[0])
        assert order_b.items[0].estimated_completion_at == run.planned_end_at
        assert order_b.items[0].eta_reliable


def test_running_free_supply_partial_then_new_run_for_remainder():
    """CASE 3：RUNNING 空余 200，新需求 500 → 200 来自 RUNNING，只新排 300。"""
    with database() as db:
        add_setting(db, line_count=2)
        product = make_product(db, "P01")
        order_a = add_order(db, "SO-A", [(product, 800)])
        run = add_running_run(db, product, 1000)
        allocate(db, run, order_a, 800)
        order_b = add_order(db, "SO-B", [(product, 500)], days_until_due=6)

        recalculate_production_plan(db, NOW)
        db.expire_all()
        runs = all_runs(db)
        assert len(runs) == 2
        allocated_to_b = sum(
            int(a.quantity)
            for a in runs[0].allocations
            if a.production_run_id == run.id and a.order_item_id == order_b.items[0].id
        )
        assert allocated_to_b == 200
        new_runs = [r for r in runs if r.id != run.id]
        assert len(new_runs) == 1
        assert int(new_runs[0].planned_quantity) == 300


def test_free_supply_never_crosses_products():
    """CASE 4：P01 的空余供给不能喂给 P02 的需求。"""
    with database() as db:
        add_setting(db, line_count=2)
        p01 = make_product(db, "P01")
        p02 = make_product(db, "P02")
        order_a = add_order(db, "SO-A", [(p01, 300)])
        run = add_running_run(db, p01, 1000, line_slot=1)
        allocate(db, run, order_a, 300)
        order_b = add_order(db, "SO-B", [(p02, 600)])

        recalculate_production_plan(db, NOW)
        db.expire_all()
        runs = all_runs(db)
        assert len(runs) == 2
        p02_runs = [r for r in runs if r.product_id == p02.id]
        assert len(p02_runs) == 1 and int(p02_runs[0].planned_quantity) == 600
        assert not [a for a in runs[0].allocations if a.order_item_id == order_b.items[0].id]
