"""Stage 7 deterministic MySQL concurrency checks.

Run explicitly with ERP_STAGE7_MYSQL=1 and ERP_DATABASE_URL pointing at a disposable
MySQL 8.4 database already migrated to head. Normal unit-test runs skip this module.
"""

from datetime import date, datetime, timedelta
import os
from pathlib import Path
import sys
from threading import Barrier, Event, Lock, Thread

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

pytestmark = pytest.mark.skipif(
    os.getenv("ERP_STAGE7_MYSQL") != "1",
    reason="requires an explicitly configured disposable MySQL audit database",
)

import app.main as main_module
from app.auth import create_access_token
from app.database import SessionLocal
from app.main import (
    confirm_order,
    create_order,
    create_order_return,
    ship_order_lines,
)
from app.models import (
    InventoryItem,
    ProductionAllocation,
    ProductionRun,
    ProductionSetting,
    SalesOrder,
    SalesOrderItem,
    StockTransaction,
    User,
)
from app.planning import recalculate_production_plan
from app.schemas import (
    OrderLinePayload,
    OrderPayload,
    OrderReturnLinePayload,
    OrderReturnPayload,
    OrderShipmentLinePayload,
    OrderShipmentPayload,
)
from app.services import create_transaction


def _product(session, sku: str, stock: float = 0) -> InventoryItem:
    row = InventoryItem(
        sku=sku,
        name=sku,
        kind="PRODUCT",
        stock_qty=stock,
        daily_capacity=100,
        mold_count=1,
        cost_price=5,
        sale_price=10,
    )
    session.add(row)
    session.flush()
    return row


def _admin_headers(session, username: str) -> dict[str, str]:
    user = User(
        username=username,
        password_hash="stage7-http-only",
        display_name=username,
        role="ADMIN",
        active=True,
    )
    session.add(user)
    session.commit()
    return {
        "Authorization": f"Bearer {create_access_token(user.id, username, 'ADMIN')}"
    }


def test_fixed_run_replacement_reuses_allocation_mysql():
    now = datetime(2026, 8, 24, 8)
    with SessionLocal() as session:
        if session.get(ProductionSetting, 1) is None:
            session.add(ProductionSetting(id=1, line_count=1))
        product = _product(session, "S7-FIXED-RUN", stock=40)
        session.commit()
        created = create_order(OrderPayload(
            customer_name="stage7",
            order_date=date(2026, 8, 24),
            required_date=date(2026, 8, 31),
            items=[OrderLinePayload(product_id=product.id, quantity=90, unit_price=10)],
        ), session)
        order_id = created["id"]
        confirm_order(order_id, session)
        order = session.scalar(select(SalesOrder).where(SalesOrder.id == order_id))
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id))
        # 确认订单生成的模拟批次由明确锁定的补库存批次替代：100 件中已有 50 件分给本行。
        for auto_run in session.scalars(select(ProductionRun).where(
            ProductionRun.product_id == product.id,
            ProductionRun.source_type == "ORDER",
            ProductionRun.status == "PLANNED",
        )).all():
            session.delete(auto_run)
        session.flush()
        run = ProductionRun(
            run_no="S7-FIXED-100",
            product_id=product.id,
            planned_quantity=100,
            planned_start_at=now,
            planned_end_at=now + timedelta(days=1),
            effective_daily_capacity=100,
            status="PLANNED",
            schedule_locked=True,
            source_type="REPLENISHMENT",
        )
        session.add(run)
        session.flush()
        session.add(ProductionAllocation(
            production_run_id=run.id,
            order_item_id=line.id,
            quantity=50,
            sequence=1,
            estimated_completion_at=run.planned_end_at,
        ))
        session.commit()

        ship_order_lines(order_id, OrderShipmentPayload(items=[
            OrderShipmentLinePayload(order_item_id=line.id, quantity=40),
        ]), session)
        create_order_return(order_id, OrderReturnPayload(
            resolution="REPLACE",
            items=[OrderReturnLinePayload(
                order_item_id=line.id,
                quantity=30,
                restock=False,
            )],
        ), session)

        allocations = session.scalars(select(ProductionAllocation).where(
            ProductionAllocation.production_run_id == run.id,
            ProductionAllocation.order_item_id == line.id,
        )).all()
        assert len(allocations) == 1
        assert int(allocations[0].quantity) == 80
        session.refresh(product)
        session.refresh(line)
        assert float(product.stock_qty) == 0
        assert int(line.shipped_quantity) == 40
        assert int(line.replacement_pending_quantity) == 30


@pytest.mark.parametrize("round_no", range(50))
def test_reverse_same_transaction_concurrently_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7-REV-{round_no:02d}")
        first = create_transaction(session, "MANUAL_IN", [(product, 50, 5)], "T1")
        session.commit()
        first_id = first.id
        product = session.get(InventoryItem, product.id)
        create_transaction(session, "MANUAL_IN", [(product, 100, 5)], "T2")
        session.commit()
        product_id = product.id
        headers = _admin_headers(session, f"s7-reverse-{round_no:02d}")

    barrier = Barrier(2)
    result_lock = Lock()
    statuses: list[int] = []

    def reverse_once() -> None:
        client = TestClient(main_module.app)
        try:
            barrier.wait()
            response = client.post(
                f"/api/stock/transactions/{first_id}/reverse",
                headers=headers,
            )
            with result_lock:
                statuses.append(response.status_code)
        finally:
            client.close()

    threads = [Thread(target=reverse_once), Thread(target=reverse_once)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()

    assert sorted(statuses) == [201, 409]
    with SessionLocal() as session:
        assert float(session.get(InventoryItem, product_id).stock_qty) == 100
        assert session.scalar(select(func.count(StockTransaction.id)).where(
            StockTransaction.reversal_of_transaction_id == first_id
        )) == 1


@pytest.mark.parametrize("round_no", range(20))
def test_draft_order_updates_are_complete_last_write_wins_mysql(round_no: int):
    with SessionLocal() as session:
        products = [
            _product(session, f"S7-ORDER-{round_no:02d}-{suffix}")
            for suffix in ("A", "B", "C")
        ]
        order = SalesOrder(
            order_no=f"S7-DRAFT-{round_no:02d}",
            customer_name="initial",
            status="DRAFT",
            order_date=date(2026, 8, 24),
            required_date=date(2026, 8, 31),
            total_amount=10,
            items=[SalesOrderItem(
                product_id=products[0].id,
                quantity=1,
                reference_price=10,
                unit_price=10,
                line_total=10,
            )],
        )
        session.add(order)
        session.commit()
        order_id = order.id
        product_ids = [product.id for product in products]
        headers = _admin_headers(session, f"s7-order-{round_no:02d}")

    payload_a = OrderPayload(
        customer_name="client-A",
        order_date=date(2026, 8, 24),
        required_date=date(2026, 8, 30),
        items=[
            OrderLinePayload(product_id=product_ids[0], quantity=2, unit_price=11),
            OrderLinePayload(product_id=product_ids[1], quantity=3, unit_price=12),
        ],
    )
    payload_b = OrderPayload(
        customer_name="client-B",
        order_date=date(2026, 8, 24),
        required_date=date(2026, 8, 29),
        items=[OrderLinePayload(product_id=product_ids[2], quantity=4, unit_price=13)],
    )
    request_ready = [Event(), Event()]
    barrier = Barrier(2)
    errors: list[BaseException] = []

    def writer(index: int, payload: OrderPayload) -> None:
        client = TestClient(main_module.app)
        try:
            request_ready[index].set()
            barrier.wait()
            response = client.put(
                f"/api/orders/{order_id}",
                json=payload.model_dump(mode="json"),
                headers=headers,
            )
            assert response.status_code == 200, response.text
        except BaseException as exc:
            errors.append(exc)
        finally:
            client.close()

    # 先由第三个事务持有父订单行锁，让两个 HTTP PUT 都进入并在同一把锁前竞争。
    with SessionLocal() as blocker:
        blocker.scalar(select(SalesOrder).where(
            SalesOrder.id == order_id
        ).with_for_update())
        threads = [
            Thread(target=writer, args=(0, payload_a)),
            Thread(target=writer, args=(1, payload_b)),
        ]
        for thread in threads:
            thread.start()
        assert all(event.wait(timeout=10) for event in request_ready)
        blocker.commit()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    assert not errors

    with SessionLocal() as session:
        order = session.scalar(select(SalesOrder).where(SalesOrder.id == order_id))
        items = session.scalars(select(SalesOrderItem).where(
            SalesOrderItem.order_id == order_id
        )).all()
        actual = (
            order.customer_name,
            tuple(sorted((item.product_id, item.quantity, float(item.unit_price)) for item in items)),
            float(order.total_amount),
        )
        expected_a = (
            "client-A",
            tuple(sorted([(product_ids[0], 2, 11.0), (product_ids[1], 3, 12.0)])),
            58.0,
        )
        expected_b = (
            "client-B",
            ((product_ids[2], 4, 13.0),),
            52.0,
        )
        assert actual in {expected_a, expected_b}
        assert float(order.total_amount) == sum(float(item.line_total) for item in items)
