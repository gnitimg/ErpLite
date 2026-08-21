from datetime import date, datetime
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import (
    _document_rows,
    _ship_order,
    cancel_order,
    complete_production_run,
    create_stock_document,
    inventory,
    update_order,
)
from app.models import (
    InventoryItem,
    ProductBomItem,
    ProductionRun,
    ProductionSetting,
    SalesOrder,
    SalesOrderItem,
    StockTransaction,
    StockTransactionItem,
)
from app.planning import purchase_requirement_summary, recalculate_production_plan
from app.schemas import (
    OrderLinePayload,
    OrderPayload,
    ProductionCompletionPayload,
    StockDocumentLinePayload,
    StockDocumentPayload,
)
from app.services import (
    load_order,
    rebalance_product_reservations,
    transaction_dict,
)


NOW = datetime(2026, 8, 21, 8, 0)


def database() -> tuple[object, Session]:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, Session(engine)


def product(db: Session, sku: str, stock: int = 0) -> InventoryItem:
    row = InventoryItem(
        sku=sku,
        name=sku,
        kind="PRODUCT",
        stock_qty=stock,
        daily_capacity=100,
        mold_count=1,
        sale_price=10,
    )
    db.add(row)
    db.flush()
    return row


def order(db: Session, order_no: str, lines: list[tuple[InventoryItem, int]]) -> SalesOrder:
    row = SalesOrder(
        order_no=order_no,
        customer_name="客户甲",
        customer_phone="123",
        customer_address="旧地址",
        status="CONFIRMED",
        order_date=date(2026, 8, 21),
        required_date=date(2026, 8, 25),
        total_amount=sum(quantity * 10 for _, quantity in lines),
    )
    row.items = [
        SalesOrderItem(
            product_id=item.id,
            quantity=quantity,
            reference_price=10,
            unit_price=10,
            line_total=quantity * 10,
        )
        for item, quantity in lines
    ]
    db.add(row)
    db.flush()
    return row


def test_partial_inventory_reserves_only_available_and_plans_remaining():
    _engine, db = database()
    with db:
        item = product(db, "P01", stock=80)
        customer_order = order(db, "SO-1", [(item, 100)])
        recalculate_production_plan(db, NOW)

        assert customer_order.items[0].reserved_quantity == 80
        assert customer_order.items[0].production_required_quantity == 20
        assert db.query(ProductionRun).one().planned_quantity == 20
        row = inventory("PRODUCT", False, None, "", db)[0]
        assert row["order_required_qty"] == 20
        assert row["gap_qty"] == -20


def test_shared_part_purchase_shortage_is_globally_aggregated():
    _engine, db = database()
    with db:
        shared = InventoryItem(
            sku="X",
            name="共享零件",
            kind="PART",
            stock_qty=150,
        )
        first = product(db, "P01")
        second = product(db, "P02")
        db.add(shared)
        db.flush()
        db.add_all([
            ProductBomItem(product_id=first.id, part_id=shared.id, quantity=1),
            ProductBomItem(product_id=second.id, part_id=shared.id, quantity=2),
        ])
        order(db, "SO-1", [(first, 100)])
        order(db, "SO-2", [(second, 100)])
        recalculate_production_plan(db, NOW)

        requirements = purchase_requirement_summary(db)
        assert len(requirements) == 1
        assert requirements[0]["total_required"] == 300
        assert requirements[0]["shortage_quantity"] == 150
        row = inventory("PART", False, None, "", db)[0]
        assert row["order_required_qty"] == 300
        assert row["gap_qty"] == -150


@pytest.mark.parametrize(
    ("actual", "expected_remaining", "expected_free"),
    [(73, 27, 0), (120, 0, 20)],
)
def test_completion_accepts_under_or_over_production(
    actual: int,
    expected_remaining: int,
    expected_free: int,
):
    _engine, db = database()
    with db:
        db.add(ProductionSetting(id=1, line_count=1))
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=1000)
        finished = product(db, "P01")
        db.add(part)
        db.flush()
        db.add(ProductBomItem(product_id=finished.id, part_id=part.id, quantity=2))
        customer_order = order(db, "SO-1", [(finished, 100)])
        recalculate_production_plan(db, NOW)
        planned = db.query(ProductionRun).filter_by(status="PLANNED").one()

        result = complete_production_run(
            planned.id,
            ProductionCompletionPayload(
                actual_quantity=actual,
                completion_date=date(2026, 8, 22),
            ),
            db,
        )

        assert result["actual_quantity"] == actual
        assert db.get(InventoryItem, part.id).stock_qty == 1000 - actual * 2
        assert db.get(InventoryItem, finished.id).stock_qty == actual
        assert customer_order.items[0].reserved_quantity == min(actual, 100)
        active = db.query(ProductionRun).filter_by(status="PLANNED").all()
        assert sum(run.planned_quantity for run in active) == expected_remaining
        assert finished.stock_qty - customer_order.items[0].reserved_quantity == expected_free
        inbound = db.get(StockTransaction, result["transaction_id"])
        assert inbound.related_production_run_id == planned.id
        assert inbound.transaction_type == "ASSEMBLY_IN"
        assert len(inbound.lines) == 1
        assert inbound.lines[0].item_id == finished.id
        consumption = db.get(
            StockTransaction,
            result["consumption_transaction_id"],
        )
        assert consumption.transaction_type == "PRODUCTION_OUT"
        assert len(consumption.lines) == 1
        assert consumption.lines[0].item_id == part.id
        assert consumption.lines[0].quantity_change == -actual * 2
        assert len(_document_rows(db, "INBOUND", "PRODUCT")) == 1
        assert len(_document_rows(db, "OUTBOUND", "PART", "零件X")) == 1
        assert len(_document_rows(
            db,
            "OUTBOUND",
            "PART",
            item_id=part.id,
        )) == 1
        assert _document_rows(
            db,
            "OUTBOUND",
            "PART",
            item_id=finished.id,
        ) == []
        assert _document_rows(db, "INBOUND", "PART") == []
        assert sum(allocation.quantity for allocation in planned.allocations) == min(actual, 100)


def test_partial_and_multi_product_shipping_updates_only_selected_lines():
    _engine, db = database()
    with db:
        first = product(db, "B", stock=100)
        second = product(db, "C", stock=200)
        customer_order = order(db, "SO-1", [(first, 100), (second, 200)])
        rebalance_product_reservations(db, {first.id, second.id})

        result = _ship_order(db, customer_order.id, {customer_order.items[0].id: 60})
        refreshed = load_order(db, customer_order.id)

        assert result["order"]["status"] == "PARTIALLY_SHIPPED"
        assert refreshed.items[0].shipped_quantity == 60
        assert refreshed.items[0].reserved_quantity == 40
        assert refreshed.items[1].shipped_quantity == 0
        assert first.stock_qty == 40
        assert second.stock_qty == 200


def test_whole_order_shipping_fulfills_once_and_rejects_duplicate():
    _engine, db = database()
    with db:
        first = product(db, "B", stock=100)
        second = product(db, "C", stock=200)
        customer_order = order(db, "SO-1", [(first, 100), (second, 200)])
        rebalance_product_reservations(db, {first.id, second.id})

        result = _ship_order(db, customer_order.id, None)
        assert result["order"]["status"] == "FULFILLED"
        assert first.stock_qty == 0
        assert second.stock_qty == 0
        transaction = db.get(StockTransaction, result["transaction_id"])
        assert len(transaction.lines) == 2

        with pytest.raises(HTTPException) as error:
            _ship_order(db, customer_order.id, None)
        assert error.value.status_code == 409
        assert first.stock_qty == 0
        assert second.stock_qty == 0


def test_first_shipment_freezes_order_and_snapshot_survives_master_rename():
    _engine, db = database()
    with db:
        finished = product(db, "B", stock=100)
        finished.name = "AAA"
        customer_order = order(db, "SO-1", [(finished, 100)])
        rebalance_product_reservations(db, {finished.id})
        result = _ship_order(db, customer_order.id, {customer_order.items[0].id: 1})

        payload = OrderPayload(
            customer_name="新客户",
            order_date=date(2026, 8, 21),
            required_date=date(2026, 8, 25),
            items=[OrderLinePayload(product_id=finished.id, quantity=99, unit_price=10)],
        )
        with pytest.raises(HTTPException) as edit_error:
            update_order(customer_order.id, payload, db)
        assert edit_error.value.status_code == 409
        with pytest.raises(HTTPException) as cancel_error:
            cancel_order(customer_order.id, db)
        assert cancel_error.value.status_code == 409

        finished.name = "BBB"
        db.flush()
        transaction = db.scalar(
            select(StockTransaction)
            .where(StockTransaction.id == result["transaction_id"])
            .options(
                selectinload(StockTransaction.lines)
                .selectinload(StockTransactionItem.item)
            )
        )
        document = transaction_dict(transaction)
        assert document["counterparty_name"] == "客户甲"
        assert document["lines"][0]["name"] == "AAA"


def test_multi_line_stock_document_updates_inventory_and_snapshots_header():
    _engine, db = database()
    with db:
        first = InventoryItem(sku="A", name="零件A", kind="PART", stock_qty=2)
        second = product(db, "B", stock=1)
        db.add(first)
        db.flush()

        document = create_stock_document(
            StockDocumentPayload(
                direction="INBOUND",
                counterparty_name="供应商甲",
                counterparty_phone="021-1234",
                counterparty_address="上海",
                occurred_date=date(2026, 8, 21),
                operator="仓管员",
                notes="采购到货",
                items=[
                    StockDocumentLinePayload(item_id=first.id, quantity=3, unit_price=2.5),
                    StockDocumentLinePayload(item_id=second.id, quantity=4, unit_price=9),
                ],
            ),
            db,
        )

        assert document["transaction_type"] == "GENERAL_IN"
        assert document["counterparty_name"] == "供应商甲"
        assert document["operator"] == "仓管员"
        assert first.stock_qty == 5
        assert second.stock_qty == 5
        assert len(document["lines"]) == 2
        assert len(_document_rows(db, "INBOUND", "PART", transaction_type="GENERAL_IN")) == 1
        assert len(_document_rows(db, "INBOUND", "PRODUCT", transaction_type="GENERAL_IN")) == 1


def test_order_shipment_accepts_editable_document_header_and_price():
    _engine, db = database()
    with db:
        finished = product(db, "P01", stock=10)
        customer_order = order(db, "SO-1", [(finished, 10)])
        rebalance_product_reservations(db, {finished.id})

        result = _ship_order(
            db,
            customer_order.id,
            {customer_order.items[0].id: 6},
            notes="本次先发六台",
            price_overrides={customer_order.items[0].id: 8.5},
            occurred_at=datetime(2026, 8, 22),
            operator="张三",
            counterparty_name="编辑后的收货单位",
            counterparty_phone="999",
            counterparty_address="新地址",
        )
        transaction = db.scalar(
            select(StockTransaction)
            .where(StockTransaction.id == result["transaction_id"])
            .options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item))
        )
        document = transaction_dict(transaction)

        assert result["transaction_no"] == document["transaction_no"]
        assert document["counterparty_name"] == "编辑后的收货单位"
        assert document["counterparty_address"] == "新地址"
        assert document["operator"] == "张三"
        assert document["lines"][0]["unit_price"] == 8.5
        assert document["lines"][0]["line_total"] == 51
