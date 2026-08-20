from datetime import date, datetime, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import (
    InventoryItem,
    Mold,
    ProductBomItem,
    ProductionCapability,
    ProductionAllocation,
    ProductionLine,
    ProductionRun,
    SalesOrder,
    SalesOrderItem,
)
from app.planning import recalculate_production_plan


NOW = datetime(2026, 8, 20, 8, 0, 0)


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


def add_capability(
    db: Session,
    product: InventoryItem,
    line_code: str,
    mold_code: str,
    daily_capacity: float,
) -> ProductionCapability:
    line = db.query(ProductionLine).filter_by(code=line_code).one_or_none()
    if line is None:
        line = ProductionLine(code=line_code, name=line_code)
        db.add(line)
    mold = db.query(Mold).filter_by(code=mold_code).one_or_none()
    if mold is None:
        mold = Mold(code=mold_code, name=mold_code)
        db.add(mold)
    db.flush()
    capability = ProductionCapability(
        product_id=product.id,
        line_id=line.id,
        mold_id=mold.id,
        nominal_daily_capacity=daily_capacity,
        safety_factor=1,
    )
    db.add(capability)
    db.flush()
    return capability


def make_product(db: Session, sku: str, stock: int = 0) -> InventoryItem:
    product = InventoryItem(sku=sku, name=sku, kind="PRODUCT", stock_qty=stock)
    db.add(product)
    db.flush()
    return product


def test_single_line_eta_and_two_products_run_in_parallel():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        first = make_product(db, "P01")
        second = make_product(db, "P02")
        add_capability(db, first, "L01", "M01", 10000)
        add_capability(db, second, "L02", "M02", 5000)
        order = add_order(db, "SO-1", [(first, 10000), (second, 10000)])
        recalculate_production_plan(db, NOW)

        assert order.items[0].estimated_completion_at == NOW + timedelta(days=1)
        assert order.items[1].estimated_completion_at == NOW + timedelta(days=2)
        assert order.estimated_completion_at == NOW + timedelta(days=2)
        assert db.query(ProductionRun).count() == 2


def test_same_product_orders_merge_and_receive_different_eta():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        product = make_product(db, "P01")
        add_capability(db, product, "L01", "M01", 10000)
        short = add_order(db, "SO-B", [(product, 2000)], days_until_due=1)
        long = add_order(db, "SO-A", [(product, 8000)], days_until_due=2)
        recalculate_production_plan(db, NOW)

        runs = db.query(ProductionRun).all()
        assert len(runs) == 1
        assert runs[0].planned_quantity == 10000
        assert short.items[0].estimated_completion_at == NOW + timedelta(days=0.2)
        assert long.items[0].estimated_completion_at == NOW + timedelta(days=1)


def test_single_mold_prevents_parallel_and_two_molds_allow_parallel():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        single = make_product(db, "SINGLE")
        add_capability(db, single, "L01", "M01", 10000)
        add_capability(db, single, "L02", "M01", 10000)
        add_order(db, "SO-S", [(single, 20000)])
        recalculate_production_plan(db, NOW)
        single_runs = db.query(ProductionRun).filter_by(product_id=single.id).all()
        assert len(single_runs) == 1
        assert single_runs[0].planned_end_at == NOW + timedelta(days=2)

        for row in db.query(SalesOrder).all():
            row.status = "CANCELLED"
        parallel = make_product(db, "PARALLEL")
        add_capability(db, parallel, "L01", "M02", 10000)
        add_capability(db, parallel, "L02", "M03", 10000)
        add_order(db, "SO-P", [(parallel, 20000)])
        recalculate_production_plan(db, NOW)
        parallel_runs = db.query(ProductionRun).filter_by(product_id=parallel.id).all()
        assert len(parallel_runs) == 2
        assert {run.planned_end_at for run in parallel_runs} == {NOW + timedelta(days=1)}


def test_inventory_is_not_promised_twice_and_bom_shortage_marks_eta_unreliable():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        part = InventoryItem(sku="PART", name="PART", kind="PART", stock_qty=100)
        product = make_product(db, "P01", stock=1000)
        db.add(part)
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=1))
        add_capability(db, product, "L01", "M01", 1000)
        first = add_order(db, "SO-A", [(product, 800)], days_until_due=1)
        second = add_order(db, "SO-B", [(product, 800)], days_until_due=2)
        result = recalculate_production_plan(db, NOW)

        assert first.items[0].reserved_quantity == 800
        assert second.items[0].reserved_quantity == 200
        assert second.items[0].production_required_quantity == 600
        assert result["material_shortage_product_ids"] == [product.id]
        assert second.estimated_completion_at == NOW + timedelta(days=0.6)
        assert second.eta_reliable is False
        assert "原材料不足" in second.eta_note


def test_existing_running_resource_pushes_new_plan_start():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        old_product = make_product(db, "OLD")
        product = make_product(db, "NEW")
        capability = add_capability(db, product, "L01", "M01", 10000)
        db.add(ProductionRun(
            run_no="RUNNING-1",
            product_id=old_product.id,
            line_id=capability.line_id,
            mold_id=capability.mold_id,
            planned_quantity=10000,
            produced_quantity=0,
            planned_start_at=NOW,
            planned_end_at=NOW + timedelta(days=1),
            effective_daily_capacity=10000,
            status="RUNNING",
        ))
        order = add_order(db, "SO-NEW", [(product, 10000)])
        recalculate_production_plan(db, NOW)

        planned = db.query(ProductionRun).filter_by(status="PLANNED").one()
        assert planned.planned_start_at == NOW + timedelta(days=1)
        assert order.estimated_completion_at == NOW + timedelta(days=2)


def test_running_allocation_is_not_scheduled_twice():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        product = make_product(db, "P01")
        capability = add_capability(db, product, "L01", "M01", 10000)
        order = add_order(db, "SO-1", [(product, 10000)])
        run = ProductionRun(
            run_no="RUNNING-1",
            product_id=product.id,
            line_id=capability.line_id,
            mold_id=capability.mold_id,
            planned_quantity=10000,
            produced_quantity=0,
            planned_start_at=NOW,
            planned_end_at=NOW + timedelta(days=1),
            effective_daily_capacity=10000,
            status="RUNNING",
        )
        db.add(run)
        db.flush()
        db.add(ProductionAllocation(
            production_run_id=run.id,
            order_item_id=order.items[0].id,
            quantity=10000,
            sequence=1,
            estimated_completion_at=NOW + timedelta(days=1),
        ))

        result = recalculate_production_plan(db, NOW)

        assert result["created_run_count"] == 0
        assert db.query(ProductionRun).count() == 1
        assert order.estimated_completion_at == NOW + timedelta(days=1)
