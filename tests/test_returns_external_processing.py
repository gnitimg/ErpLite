from datetime import date, datetime
from pathlib import Path
import sys

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import (
    _ship_order,
    complete_production_run,
    create_order_return,
    return_external_processing,
    send_external_processing,
)
from app.models import (
    ExternalProcessingBatch,
    InventoryItem,
    ProductBomItem,
    ProductionRun,
    ProductionSetting,
    SalesOrder,
    SalesOrderItem,
    StockTransaction,
)
from app.planning import recalculate_production_plan
from app.schemas import (
    ExternalProcessingReturnPayload,
    ExternalProcessingSendPayload,
    OrderReturnLinePayload,
    OrderReturnPayload,
    ProductionCompletionPayload,
)
from app.services import load_order, order_workflow_dict, rebalance_product_reservations


NOW = datetime(2026, 8, 22, 8, 0)


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_order(
    db: Session,
    product: InventoryItem,
    order_no: str,
    quantity: int,
    required_date: date = date(2026, 8, 25),
) -> SalesOrder:
    order = SalesOrder(
        order_no=order_no,
        customer_name="客户",
        status="CONFIRMED",
        order_date=date(2026, 8, 22),
        required_date=required_date,
        total_amount=quantity * 10,
    )
    order.items = [SalesOrderItem(
        product_id=product.id,
        quantity=quantity,
        reference_price=10,
        unit_price=10,
        line_total=quantity * 10,
    )]
    db.add(order)
    db.flush()
    return order


def test_workflow_explains_stock_reserved_by_earlier_order():
    with database() as db:
        part = InventoryItem(sku="PART", name="零件", kind="PART", stock_qty=100)
        product = InventoryItem(
            sku="PRODUCT",
            name="成品",
            kind="PRODUCT",
            stock_qty=58,
            daily_capacity=10,
        )
        db.add_all([part, product])
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=1))
        make_order(db, product, "SO-EARLY", 58, date(2026, 8, 23))
        later = make_order(db, product, "SO-LATER", 1, date(2026, 8, 24))

        recalculate_production_plan(db, NOW)
        workflow = order_workflow_dict(db, load_order(db, later.id))
        line = workflow["product_lines"][0]

        assert line["current_stock"] == 58
        assert line["reserved_by_other_orders"] == 58
        assert line["reserved_quantity"] == 0
        assert line["production_required"] == 1
        assert line["waiting_for_earlier_orders"] is True
        assert workflow["next_action"] == "PRODUCE"


def test_external_processing_uses_pipeline_without_duplicate_production():
    with database() as db:
        db.add(ProductionSetting(id=1, line_count=1))
        part = InventoryItem(sku="PART", name="零件", kind="PART", stock_qty=100)
        product = InventoryItem(
            sku="PRODUCT",
            name="喷漆产品",
            kind="PRODUCT",
            stock_qty=0,
            daily_capacity=10,
            mold_count=1,
            requires_external_processing=True,
            external_process_name="喷漆",
        )
        db.add_all([part, product])
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=1))
        order = make_order(db, product, "SO-1", 10)
        recalculate_production_plan(db, NOW)
        run = db.query(ProductionRun).filter_by(status="PLANNED").one()

        completed = complete_production_run(
            run.id,
            ProductionCompletionPayload(
                actual_quantity=10,
                completion_date=date(2026, 8, 22),
            ),
            db,
        )

        assert completed["inventory_bucket"] == "SEMI_FINISHED"
        assert product.stock_qty == 0
        assert product.semi_finished_qty == 10
        assert product.processing_qty == 0
        assert order.items[0].pipeline_quantity == 10
        assert order.items[0].production_required_quantity == 0
        assert db.query(ProductionRun).filter_by(status="PLANNED").count() == 0
        assert db.get(StockTransaction, completed["transaction_id"]).transaction_type == "SEMI_FINISHED_IN"

        batch_result = send_external_processing(
            ExternalProcessingSendPayload(
                product_id=product.id,
                quantity=10,
                supplier="加工商",
                occurred_date=date(2026, 8, 23),
            ),
            db,
        )
        batch = db.get(ExternalProcessingBatch, batch_result["id"])
        assert product.semi_finished_qty == 0
        assert product.processing_qty == 10
        assert order.items[0].production_required_quantity == 0

        returned = return_external_processing(
            batch.id,
            ExternalProcessingReturnPayload(
                quantity=10,
                occurred_date=date(2026, 8, 24),
            ),
            db,
        )
        assert returned["batch"]["status"] == "RETURNED"
        assert product.processing_qty == 0
        assert product.stock_qty == 10
        assert load_order(db, order.id).items[0].reserved_quantity == 10
        assert load_order(db, order.id).status == "READY_TO_SHIP"


def test_partial_return_optionally_restocks_and_cannot_exceed_shipped():
    with database() as db:
        product = InventoryItem(
            sku="PRODUCT",
            name="成品",
            kind="PRODUCT",
            stock_qty=10,
            daily_capacity=10,
        )
        db.add(product)
        db.flush()
        order = make_order(db, product, "SO-RETURN", 10)
        rebalance_product_reservations(db, {product.id})
        _ship_order(db, order.id, {order.items[0].id: 6})

        result = create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(
                    order_item_id=order.items[0].id,
                    quantity=2,
                    restock=True,
                )],
                occurred_date=date(2026, 8, 23),
                notes="客户部分退货",
            ),
            db,
        )
        refreshed = load_order(db, order.id)
        assert product.stock_qty == 6
        assert refreshed.items[0].returned_quantity == 2
        assert result["order"]["items"][0]["returnable_quantity"] == 4
        assert db.get(StockTransaction, result["transaction_id"]).transaction_type == "SALE_RETURN_IN"

        with pytest.raises(HTTPException) as error:
            create_order_return(
                order.id,
                OrderReturnPayload(items=[OrderReturnLinePayload(
                    order_item_id=order.items[0].id,
                    quantity=5,
                    restock=False,
                )]),
                db,
            )
        assert error.value.status_code == 409
        assert product.stock_qty == 6
