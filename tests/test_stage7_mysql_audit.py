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
    CustomerCredit,
    ExternalProcessingBatch,
    InventoryItem,
    OrderReturn,
    Payment,
    ProductionAllocation,
    ProductBomItem,
    ProductionRun,
    ProductionSetting,
    Receivable,
    SalesOrder,
    SalesOrderItem,
    StockReservation,
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


def _http_order_race(
    order_id: int,
    headers: dict[str, str],
    calls: list[tuple[str, str, dict | None]],
) -> list[int]:
    """让两个独立 HTTP client 同时在同一 SalesOrder 行锁前竞争。"""
    barrier = Barrier(len(calls))
    ready = [Event() for _ in calls]
    result_lock = Lock()
    statuses: list[int] = []
    errors: list[BaseException] = []

    def request_once(index: int, method: str, path: str, body: dict | None) -> None:
        client = TestClient(main_module.app)
        try:
            ready[index].set()
            barrier.wait()
            response = client.request(method, path, json=body, headers=headers)
            with result_lock:
                statuses.append(response.status_code)
        except BaseException as exc:
            errors.append(exc)
        finally:
            client.close()

    with SessionLocal() as blocker:
        blocker.scalar(select(SalesOrder).where(
            SalesOrder.id == order_id
        ).with_for_update())
        threads = [
            Thread(target=request_once, args=(index, *call))
            for index, call in enumerate(calls)
        ]
        for thread in threads:
            thread.start()
        assert all(event.wait(timeout=10) for event in ready)
        blocker.commit()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    assert not errors
    assert len(statuses) == len(calls)
    assert not [status for status in statuses if status >= 500]
    return statuses


def _draft_order(session, prefix: str, product: InventoryItem, quantity: int = 10) -> SalesOrder:
    order = SalesOrder(
        order_no=f"S7-{prefix}-SO",
        customer_name=prefix,
        status="DRAFT",
        order_date=date(2026, 8, 24),
        required_date=date(2026, 8, 31),
        total_amount=quantity * 10,
        items=[SalesOrderItem(
            product_id=product.id,
            quantity=quantity,
            reference_price=10,
            unit_price=10,
            line_total=quantity * 10,
        )],
    )
    session.add(order)
    session.commit()
    return order


def _shipped_order(
    session,
    prefix: str,
    *,
    quantity: int = 10,
    shipped_quantity: int | None = None,
) -> tuple[int, int, int, int, int]:
    """Create a confirmed order and one committed SALE_OUT/Receivable fact."""
    shipped_quantity = shipped_quantity or quantity
    product = _product(session, f"{prefix}-PRODUCT", stock=quantity)
    order = _draft_order(session, prefix, product, quantity)
    confirm_order(order.id, session)
    line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id))
    shipment = ship_order_lines(order.id, OrderShipmentPayload(items=[
        OrderShipmentLinePayload(order_item_id=line.id, quantity=shipped_quantity),
    ]), session)
    receivable = session.scalar(select(Receivable).where(
        Receivable.related_stock_transaction_id == shipment["transaction_id"]
    ))
    assert receivable is not None
    return order.id, line.id, product.id, shipment["transaction_id"], receivable.id


def _add_bom_and_running_run(session, product: InventoryItem, prefix: str, quantity: int = 10) -> ProductionRun:
    part = InventoryItem(
        sku=f"{prefix}-PART",
        name=f"{prefix}-PART",
        kind="PART",
        stock_qty=quantity * 10,
        cost_price=1,
        supply_mode="STOCK",
    )
    session.add(part)
    session.flush()
    session.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=1))
    now = datetime(2026, 8, 24, 8)
    run = ProductionRun(
        run_no=f"{prefix}-RUN",
        product_id=product.id,
        planned_quantity=quantity,
        planned_start_at=now,
        planned_end_at=now + timedelta(hours=1),
        actual_start_at=now,
        effective_daily_capacity=100,
        status="RUNNING",
        workflow_version=2,
        source_type="REPLENISHMENT",
    )
    session.add(run)
    session.commit()
    return run


def _external_batch(session, product: InventoryItem, prefix: str, quantity: int = 10) -> ExternalProcessingBatch:
    product.requires_external_processing = True
    product.external_process_name = "PAINT"
    product.processing_qty = quantity
    outbound = create_transaction(
        session,
        "PROCESS_OUT",
        [(product, -quantity, product.cost_price)],
        f"{prefix} outbound",
        apply_inventory=False,
    )
    batch = ExternalProcessingBatch(
        batch_no=f"{prefix}-BATCH",
        product_id=product.id,
        process_name_snapshot="PAINT",
        supplier="stage7",
        quantity=quantity,
        returned_quantity=0,
        status="SENT",
        outbound_transaction_id=outbound.id,
        sent_at=datetime(2026, 8, 24, 8),
        processing_cost=0,
    )
    session.add(batch)
    session.commit()
    return batch


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


@pytest.mark.parametrize("round_no", range(20))
def test_update_and_confirm_share_lifecycle_lock_mysql(round_no: int):
    with SessionLocal() as session:
        product_a = _product(session, f"S7-R-{round_no:02d}-A")
        product_b = _product(session, f"S7-R-{round_no:02d}-B")
        order = _draft_order(session, f"R-{round_no:02d}", product_a)
        order_id = order.id
        headers = _admin_headers(session, f"s7-r-{round_no:02d}")
        product_a_id, product_b_id = product_a.id, product_b.id

    update_payload = OrderPayload(
        customer_name=f"R-{round_no:02d}-updated",
        order_date=date(2026, 8, 24),
        required_date=date(2026, 8, 30),
        items=[OrderLinePayload(product_id=product_b_id, quantity=12, unit_price=11)],
    )
    statuses = _http_order_race(order_id, headers, [
        ("PUT", f"/api/orders/{order_id}", update_payload.model_dump(mode="json")),
        ("POST", f"/api/orders/{order_id}/confirm", None),
    ])
    assert sorted(statuses) in ([200, 200], [200, 409])

    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        items = session.scalars(select(SalesOrderItem).where(
            SalesOrderItem.order_id == order_id
        )).all()
        assert len(items) == 1
        final_product_id = items[0].product_id
        assert final_product_id in {product_a_id, product_b_id}
        assert order.status in {"CONFIRMED", "WAITING_MATERIALS", "READY_TO_SHIP"}
        if final_product_id == product_b_id:
            assert sorted(statuses) == [200, 200]
        else:
            assert sorted(statuses) == [200, 409]
        reservations = session.scalars(
            select(StockReservation)
            .join(SalesOrderItem, SalesOrderItem.id == StockReservation.order_item_id)
            .where(SalesOrderItem.order_id == order_id)
        ).all()
        assert all(row.product_id == final_product_id for row in reservations)
        allocation_products = session.scalars(
            select(ProductionRun.product_id)
            .join(ProductionAllocation, ProductionAllocation.production_run_id == ProductionRun.id)
            .join(SalesOrderItem, SalesOrderItem.id == ProductionAllocation.order_item_id)
            .where(SalesOrderItem.order_id == order_id)
        ).all()
        assert all(product_id == final_product_id for product_id in allocation_products)
        assert float(order.total_amount) == sum(float(item.line_total) for item in items)


@pytest.mark.parametrize("round_no", range(20))
def test_confirm_and_cancel_never_resurrect_cancelled_order_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7-S-{round_no:02d}")
        order = _draft_order(session, f"S-{round_no:02d}", product)
        order_id = order.id
        headers = _admin_headers(session, f"s7-s-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/confirm", None),
        ("POST", f"/api/orders/{order_id}/cancel", None),
    ])
    assert sorted(statuses) in ([200, 200], [200, 409])

    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        assert order.status == "CANCELLED"
        active_run_count = session.scalar(
            select(func.count(ProductionRun.id))
            .join(ProductionAllocation, ProductionAllocation.production_run_id == ProductionRun.id)
            .join(SalesOrderItem, SalesOrderItem.id == ProductionAllocation.order_item_id)
            .where(
                SalesOrderItem.order_id == order_id,
                ProductionRun.status.in_(("PLANNED", "RUNNING")),
            )
        )
        assert active_run_count == 0


@pytest.mark.parametrize("round_no", range(50))
def test_cancel_and_ship_have_only_serial_outcomes_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7-T-{round_no:02d}", stock=10)
        order = _draft_order(session, f"T-{round_no:02d}", product)
        order_id = order.id
        confirm_order(order_id, session)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id))
        line_id, product_id = line.id, product.id
        headers = _admin_headers(session, f"s7-t-{round_no:02d}")

    ship_payload = OrderShipmentPayload(items=[
        OrderShipmentLinePayload(order_item_id=line_id, quantity=10),
    ]).model_dump(mode="json")
    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/cancel", None),
        ("POST", f"/api/orders/{order_id}/ship", ship_payload),
    ])
    assert sorted(statuses) in ([200, 409], [201, 409])

    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        line = session.get(SalesOrderItem, line_id)
        product = session.get(InventoryItem, product_id)
        sale_out_count = session.scalar(select(func.count(StockTransaction.id)).where(
            StockTransaction.related_order_id == order_id,
            StockTransaction.transaction_type == "SALE_OUT",
        ))
        if order.status == "CANCELLED":
            assert int(line.shipped_quantity or 0) == 0
            assert float(product.stock_qty) == 10
            assert sale_out_count == 0
            assert sorted(statuses) == [200, 409]
        else:
            assert order.status == "FULFILLED"
            assert int(line.shipped_quantity or 0) == 10
            assert float(product.stock_qty) == 0
            assert sale_out_count == 1
            assert sorted(statuses) == [201, 409]


@pytest.mark.parametrize("round_no", range(20))
def test_confirm_and_confirm_execute_once_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7-U-{round_no:02d}")
        order = _draft_order(session, f"U-{round_no:02d}", product)
        order_id = order.id
        line_id = order.items[0].id
        headers = _admin_headers(session, f"s7-u-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/confirm", None),
        ("POST", f"/api/orders/{order_id}/confirm", None),
    ])
    assert sorted(statuses) == [200, 409]

    with SessionLocal() as session:
        reservation_count = session.scalar(select(func.count(StockReservation.id)).where(
            StockReservation.order_item_id == line_id
        ))
        allocations = session.scalars(select(ProductionAllocation).where(
            ProductionAllocation.order_item_id == line_id
        )).all()
        pairs = {(row.production_run_id, row.order_item_id) for row in allocations}
        assert reservation_count == 1
        assert len(allocations) == len(pairs)
        assert len(allocations) == 1


@pytest.mark.parametrize("round_no", range(50))
def test_sale_out_reverse_and_payment_are_serial_mysql(round_no: int):
    with SessionLocal() as session:
        order_id, _line_id, _product_id, tx_id, receivable_id = _shipped_order(
            session, f"S7I-V-{round_no:02d}"
        )
        receivable = session.get(Receivable, receivable_id)
        payment = Payment(
            payment_no=f"S7I-V-PAY-{round_no:02d}",
            customer_name=receivable.customer_name,
            amount=receivable.amount,
            payment_date=date(2026, 8, 24),
            method="BANK",
        )
        session.add(payment)
        session.commit()
        payment_id = payment.id
        amount = float(receivable.amount)
        headers = _admin_headers(session, f"s7i-v-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/stock/transactions/{tx_id}/reverse", None),
        ("POST", f"/api/finance/payments/{payment_id}/allocate", {
            "receivable_id": receivable_id,
            "amount": amount,
        }),
    ])
    assert sorted(statuses) == [201, 409]

    with SessionLocal() as session:
        receivable = session.get(Receivable, receivable_id)
        payment = session.get(Payment, payment_id)
        original = session.get(StockTransaction, tx_id)
        assert not (
            receivable.status == "CANCELLED"
            and float(receivable.settled_amount or 0) > 0
        )
        if original.status == "REVERSED":
            assert receivable.status == "CANCELLED"
            assert float(receivable.settled_amount or 0) == 0
            assert float(payment.allocated_amount or 0) == 0
        else:
            assert float(receivable.settled_amount or 0) == amount
            assert float(payment.allocated_amount or 0) == amount


@pytest.mark.parametrize("round_no", range(50))
def test_sale_out_reverse_and_return_are_serial_mysql(round_no: int):
    with SessionLocal() as session:
        order_id, line_id, _product_id, tx_id, _receivable_id = _shipped_order(
            session, f"S7I-W-{round_no:02d}"
        )
        headers = _admin_headers(session, f"s7i-w-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/stock/transactions/{tx_id}/reverse", None),
        ("POST", f"/api/orders/{order_id}/returns", {
            "resolution": "REFUND",
            "items": [{"order_item_id": line_id, "quantity": 10, "restock": True}],
        }),
    ])
    assert sorted(statuses) == [201, 409]

    with SessionLocal() as session:
        original = session.get(StockTransaction, tx_id)
        return_count = session.scalar(select(func.count(OrderReturn.id)).where(
            OrderReturn.order_item_id == line_id
        ))
        assert not (original.status == "REVERSED" and return_count > 0)


@pytest.mark.parametrize("round_no", range(50))
def test_sale_out_reverse_and_ship_preserve_facts_mysql(round_no: int):
    with SessionLocal() as session:
        order_id, line_id, product_id, tx_id, _receivable_id = _shipped_order(
            session,
            f"S7I-X-{round_no:02d}",
            quantity=20,
            shipped_quantity=10,
        )
        headers = _admin_headers(session, f"s7i-x-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/stock/transactions/{tx_id}/reverse", None),
        ("POST", f"/api/orders/{order_id}/ship", {
            "items": [{"order_item_id": line_id, "quantity": 10}],
        }),
    ])
    assert statuses.count(201) == 2

    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        line = session.get(SalesOrderItem, line_id)
        product = session.get(InventoryItem, product_id)
        original = session.get(StockTransaction, tx_id)
        assert original.status == "REVERSED"
        assert int(line.shipped_quantity or 0) == 10
        assert float(product.stock_qty) == 10
        assert order.status == "PARTIALLY_SHIPPED"
        active_sales = session.scalar(select(func.count(StockTransaction.id)).where(
            StockTransaction.related_order_id == order_id,
            StockTransaction.transaction_type == "SALE_OUT",
            StockTransaction.status != "REVERSED",
        ))
        assert active_sales == 1


@pytest.mark.parametrize("round_no", range(50))
def test_sale_out_reverse_and_cancel_preserve_lifecycle_mysql(round_no: int):
    with SessionLocal() as session:
        order_id, line_id, product_id, tx_id, _receivable_id = _shipped_order(
            session, f"S7I-Y-{round_no:02d}"
        )
        headers = _admin_headers(session, f"s7i-y-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/stock/transactions/{tx_id}/reverse", None),
        ("POST", f"/api/orders/{order_id}/cancel", None),
    ])
    assert 201 in statuses
    assert sorted(statuses) in ([200, 201], [201, 409])

    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        line = session.get(SalesOrderItem, line_id)
        product = session.get(InventoryItem, product_id)
        assert int(line.shipped_quantity or 0) == 0
        assert float(product.stock_qty) == 10
        if order.status == "CANCELLED":
            assert int(line.reserved_quantity or 0) == 0


@pytest.mark.parametrize("round_no", range(30))
def test_payment_and_refund_cannot_double_consume_receivable_mysql(round_no: int):
    with SessionLocal() as session:
        order_id, line_id, _product_id, _tx_id, receivable_id = _shipped_order(
            session, f"S7I-PAYREF-{round_no:02d}"
        )
        receivable = session.get(Receivable, receivable_id)
        payment = Payment(
            payment_no=f"S7I-PAYREF-PAY-{round_no:02d}",
            customer_name=receivable.customer_name,
            amount=receivable.amount,
            payment_date=date(2026, 8, 24),
            method="BANK",
        )
        session.add(payment)
        session.commit()
        payment_id = payment.id
        amount = float(receivable.amount)
        headers = _admin_headers(session, f"s7i-payref-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/finance/payments/{payment_id}/allocate", {
            "receivable_id": receivable_id,
            "amount": amount,
        }),
        ("POST", f"/api/orders/{order_id}/returns", {
            "resolution": "REFUND",
            "items": [{"order_item_id": line_id, "quantity": 10, "restock": True}],
        }),
    ])
    assert not [status for status in statuses if status >= 500]

    with SessionLocal() as session:
        receivable = session.get(Receivable, receivable_id)
        offset = session.scalar(select(func.coalesce(func.sum(CustomerCredit.amount), 0)).where(
            CustomerCredit.receivable_id == receivable_id,
            CustomerCredit.kind == "OFFSET_RECEIVABLE",
        ))
        assert float(receivable.settled_amount or 0) + float(offset or 0) <= float(receivable.amount) + 1e-9


@pytest.mark.parametrize("round_no", range(50))
def test_rb1_cancel_and_inbound_never_resurrect_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7M-RB1-{round_no:02d}", stock=0)
        order = _draft_order(session, f"M-RB1-{round_no:02d}", product)
        confirm_order(order.id, session)
        order_id, product_id = order.id, product.id
        headers = _admin_headers(session, f"s7m-rb1-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/cancel", None),
        ("POST", "/api/stock/inbound", {
            "item_id": product_id, "quantity": 10, "unit_cost": 5,
        }),
    ])
    assert 200 in statuses and 201 in statuses
    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id))
        assert order.status == "CANCELLED"
        assert int(line.reserved_quantity or 0) == 0


@pytest.mark.parametrize("round_no", range(50))
def test_rb2_cancel_and_completion_never_resurrect_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7M-RB2-{round_no:02d}", stock=0)
        run = _add_bom_and_running_run(session, product, f"S7M-RB2-{round_no:02d}")
        order = _draft_order(session, f"M-RB2-{round_no:02d}", product)
        confirm_order(order.id, session)
        order_id, run_id = order.id, run.id
        headers = _admin_headers(session, f"s7m-rb2-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/cancel", None),
        ("POST", f"/api/production/runs/{run_id}/complete", {
            "qualified_quantity": 10,
            "scrap_quantity": 0,
            "completion_date": "2026-08-24",
        }),
    ])
    assert not [status for status in statuses if status >= 500]
    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id))
        if 200 in statuses:
            assert order.status == "CANCELLED"
            assert int(line.reserved_quantity or 0) == 0


@pytest.mark.parametrize("round_no", range(30))
def test_rb3_cancel_and_external_return_never_resurrect_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7M-RB3-{round_no:02d}", stock=0)
        batch = _external_batch(session, product, f"S7M-RB3-{round_no:02d}")
        order = _draft_order(session, f"M-RB3-{round_no:02d}", product)
        confirm_order(order.id, session)
        order_id, batch_id = order.id, batch.id
        headers = _admin_headers(session, f"s7m-rb3-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/cancel", None),
        ("POST", f"/api/external-processing/{batch_id}/return", {
            "quantity": 10, "occurred_date": "2026-08-24",
        }),
    ])
    assert not [status for status in statuses if status >= 500]
    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id))
        if 200 in statuses:
            assert order.status == "CANCELLED"
            assert int(line.reserved_quantity or 0) == 0


@pytest.mark.parametrize("round_no", range(50))
def test_rb4_cancel_and_manual_recalc_never_resurrect_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7M-RB4-{round_no:02d}", stock=0)
        order = _draft_order(session, f"M-RB4-{round_no:02d}", product)
        confirm_order(order.id, session)
        order_id = order.id
        headers = _admin_headers(session, f"s7m-rb4-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/cancel", None),
        ("POST", "/api/production/plan/recalculate", None),
    ])
    assert not [status for status in statuses if status >= 500]
    with SessionLocal() as session:
        order = session.get(SalesOrder, order_id)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id))
        if 200 in statuses:
            assert order.status == "CANCELLED"
            assert int(line.reserved_quantity or 0) == 0


@pytest.mark.parametrize("round_no", range(50))
def test_d1_ship_and_completion_preserve_stock_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7M-D1-{round_no:02d}", stock=10)
        run = _add_bom_and_running_run(session, product, f"S7M-D1-{round_no:02d}")
        order = _draft_order(session, f"M-D1-{round_no:02d}", product)
        confirm_order(order.id, session)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id))
        order_id, line_id, product_id, run_id = order.id, line.id, product.id, run.id
        headers = _admin_headers(session, f"s7m-d1-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/ship", {
            "items": [{"order_item_id": line_id, "quantity": 10}],
        }),
        ("POST", f"/api/production/runs/{run_id}/complete", {
            "qualified_quantity": 10,
            "scrap_quantity": 0,
            "completion_date": "2026-08-24",
        }),
    ])
    assert statuses.count(201) == 2
    with SessionLocal() as session:
        assert int(session.get(SalesOrderItem, line_id).shipped_quantity or 0) == 10
        assert float(session.get(InventoryItem, product_id).stock_qty) == 10


@pytest.mark.parametrize("round_no", range(50))
def test_d2_ship_and_inbound_preserve_stock_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7M-D2-{round_no:02d}", stock=10)
        order = _draft_order(session, f"M-D2-{round_no:02d}", product)
        confirm_order(order.id, session)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id))
        order_id, line_id, product_id = order.id, line.id, product.id
        headers = _admin_headers(session, f"s7m-d2-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/ship", {
            "items": [{"order_item_id": line_id, "quantity": 10}],
        }),
        ("POST", "/api/stock/inbound", {
            "item_id": product_id, "quantity": 10, "unit_cost": 5,
        }),
    ])
    assert statuses.count(201) == 2
    with SessionLocal() as session:
        assert int(session.get(SalesOrderItem, line_id).shipped_quantity or 0) == 10
        assert float(session.get(InventoryItem, product_id).stock_qty) == 10


@pytest.mark.parametrize("round_no", range(50))
def test_d5_return_and_completion_preserve_stock_mysql(round_no: int):
    with SessionLocal() as session:
        order_id, line_id, product_id, _tx_id, _receivable_id = _shipped_order(
            session, f"S7M-D5-{round_no:02d}"
        )
        product = session.get(InventoryItem, product_id)
        run = _add_bom_and_running_run(session, product, f"S7M-D5-{round_no:02d}")
        run_id = run.id
        headers = _admin_headers(session, f"s7m-d5-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", f"/api/orders/{order_id}/returns", {
            "resolution": "REFUND",
            "items": [{"order_item_id": line_id, "quantity": 10, "restock": True}],
        }),
        ("POST", f"/api/production/runs/{run_id}/complete", {
            "qualified_quantity": 10,
            "scrap_quantity": 0,
            "completion_date": "2026-08-24",
        }),
    ])
    assert statuses.count(201) == 2
    with SessionLocal() as session:
        line = session.get(SalesOrderItem, line_id)
        assert int(line.returned_quantity or 0) == 10
        assert float(session.get(InventoryItem, product_id).stock_qty) == 20


@pytest.mark.parametrize("round_no", range(50))
def test_d6_manual_recalc_and_ship_preserve_facts_mysql(round_no: int):
    with SessionLocal() as session:
        product = _product(session, f"S7M-D6-{round_no:02d}", stock=10)
        order = _draft_order(session, f"M-D6-{round_no:02d}", product)
        confirm_order(order.id, session)
        line = session.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order.id))
        order_id, line_id, product_id = order.id, line.id, product.id
        headers = _admin_headers(session, f"s7m-d6-{round_no:02d}")

    statuses = _http_order_race(order_id, headers, [
        ("POST", "/api/production/plan/recalculate", None),
        ("POST", f"/api/orders/{order_id}/ship", {
            "items": [{"order_item_id": line_id, "quantity": 10}],
        }),
    ])
    assert not [status for status in statuses if status >= 500]
    with SessionLocal() as session:
        line = session.get(SalesOrderItem, line_id)
        assert int(line.shipped_quantity or 0) == 10
        assert float(session.get(InventoryItem, product_id).stock_qty) == 0
    Receivable,
