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
    _ship_order,
    allocate_payment,
    create_payment,
    create_user,
    delete_user,
    reconcile_stock,
    save_product,
    update_user,
)
from app.auth import create_access_token


class _MockRequest:
    def __init__(self, token: str | None = None):
        self._headers = {}
        if token:
            self._headers["authorization"] = f"Bearer {token}"

    @property
    def headers(self):
        return self._headers


def _admin_request() -> _MockRequest:
    return _MockRequest(create_access_token(0, "admin", "ADMIN", "管理员"))
from app.models import (
    InventoryItem,
    Payment,
    PaymentAllocation,
    ProductBomItem,
    ProductionRun,
    ProductionSetting,
    Receivable,
    SalesOrder,
    SalesOrderItem,
    StockTransaction,
    User,
)
from app.planning import recalculate_production_plan
from app.schemas import (
    OrderLinePayload,
    OrderPayload,
    PaymentAllocationPayload,
    PaymentPayload,
    ProductPayload,
    BomLinePayload,
    StockReconciliationPayload,
    StockReconciliationLinePayload,
    UserPayload,
    UserUpdatePayload,
)
from app.services import (
    hash_password,
    load_order,
    rebalance_product_reservations,
    verify_password,
)


NOW = datetime(2026, 8, 22, 8, 0)


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_product(db: Session, sku: str = "P01", stock: int = 0) -> InventoryItem:
    row = InventoryItem(
        sku=sku, name=sku, kind="PRODUCT", stock_qty=stock,
        daily_capacity=100, mold_count=1, sale_price=10,
    )
    db.add(row)
    db.flush()
    return row


def make_order(db: Session, product: InventoryItem, quantity: int = 10) -> SalesOrder:
    order = SalesOrder(
        order_no="SO-1", customer_name="客户甲", status="CONFIRMED",
        order_date=date(2026, 8, 22), required_date=date(2026, 8, 25),
        total_amount=quantity * 10,
    )
    order.items = [SalesOrderItem(
        product_id=product.id, quantity=quantity,
        reference_price=10, unit_price=10, line_total=quantity * 10,
    )]
    db.add(order)
    db.flush()
    return order


def test_moving_weighted_average_cost_on_inbound():
    with database() as db:
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=10, cost_price=5)
        db.add(part)
        db.flush()
        from app.services import create_transaction
        create_transaction(db, "PURCHASE_IN", [(part, 10, 8)], "采购入库")
        db.commit()
        assert part.stock_qty == 20
        assert part.cost_price == 6.5


def test_moving_weighted_average_does_not_change_on_outbound():
    with database() as db:
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=20, cost_price=6.5)
        db.add(part)
        db.flush()
        from app.services import create_transaction
        create_transaction(db, "MANUAL_OUT", [(part, -5, 6.5)], "出库")
        db.commit()
        assert part.stock_qty == 15
        assert part.cost_price == 6.5


def test_bom_self_reference_rejected():
    with database() as db:
        product = make_product(db, "P01")
        with pytest.raises(HTTPException) as error:
            save_product(db, ProductPayload(
                sku="P01", name="P01",
                components=[BomLinePayload(part_id=product.id, quantity=1)],
            ), product)
        assert error.value.status_code == 400


def test_return_restock_semantics_per_resolution():
    """restock 勾选对所有 resolution 生效：勾了就回库，没勾就不回库。"""
    with database() as db:
        from app.main import create_order_return
        from app.schemas import OrderReturnLinePayload, OrderReturnPayload
        product = make_product(db, "P01", stock=10)
        order = make_order(db, product, 10)
        rebalance_product_reservations(db, {product.id})
        _ship_order(db, order.id, {order.items[0].id: 6})
        assert product.stock_qty == 4

        result = create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=order.items[0].id, quantity=2, restock=True)],
                resolution="REFUND",
                occurred_date=date(2026, 8, 23),
            ),
            db,
        )
        assert result["resolution"] == "REFUND"
        assert product.stock_qty == 6

        # 换货 + 勾选回库：货回仓库，同时形成待补需求
        result2 = create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=order.items[0].id, quantity=1, restock=True)],
                resolution="REPLACE",
                occurred_date=date(2026, 8, 24),
            ),
            db,
        )
        assert result2["resolution"] == "REPLACE"
        assert product.stock_qty == 7
        db.refresh(order.items[0])
        assert int(order.items[0].replacement_pending_quantity or 0) == 1

        # 换货 + 不回库（报废件）：库存不动，同样形成待补需求
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=order.items[0].id, quantity=1, restock=False)],
                resolution="REPLACE",
                occurred_date=date(2026, 8, 25),
            ),
            db,
        )
        assert product.stock_qty == 7
        db.refresh(order.items[0])
        assert int(order.items[0].replacement_pending_quantity or 0) == 2


def test_external_processing_sets_expected_return_at():
    with database() as db:
        from app.main import send_external_processing
        from app.schemas import ExternalProcessingSendPayload
        product = InventoryItem(
            sku="P01", name="喷漆产品", kind="PRODUCT", stock_qty=0,
            daily_capacity=10, mold_count=1, semi_finished_qty=10,
            requires_external_processing=True, external_process_name="喷漆",
            default_external_lead_days=5,
        )
        db.add(product)
        db.flush()
        result = send_external_processing(
            ExternalProcessingSendPayload(
                product_id=product.id, quantity=5, supplier="加工商",
                occurred_date=date(2026, 8, 22),
            ),
            db,
        )
        assert result["expected_return_at"] is not None
        assert "2026-08-27" in result["expected_return_at"]

        result2 = send_external_processing(
            ExternalProcessingSendPayload(
                product_id=product.id, quantity=3, supplier="加工商",
                occurred_date=date(2026, 8, 22), lead_days=10,
            ),
            db,
        )
        assert "2026-09-01" in result2["expected_return_at"]


def test_purchase_commitment_crud():
    with database() as db:
        from app.main import create_purchase_commitment, list_purchase_commitments, update_purchase_commitment_status, delete_purchase_commitment
        from app.schemas import PurchaseCommitmentPayload, PurchaseCommitmentStatusPayload
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=0)
        db.add(part)
        db.flush()
        commitment = create_purchase_commitment(
            PurchaseCommitmentPayload(
                part_id=part.id, quantity=100,
                expected_arrival_date=date(2026, 8, 30),
                supplier_text="供应商A",
            ),
            db,
        )
        assert commitment["status"] == "PLANNED"
        assert commitment["quantity"] == 100

        updated = update_purchase_commitment_status(
            commitment["id"],
            PurchaseCommitmentStatusPayload(status="ARRIVED"),
            db,
        )
        assert updated["status"] == "ARRIVED"

        commitment2 = create_purchase_commitment(
            PurchaseCommitmentPayload(
                part_id=part.id, quantity=50,
                expected_arrival_date=date(2026, 9, 1),
            ),
            db,
        )
        delete_purchase_commitment(commitment2["id"], db)
        all_commitments = list_purchase_commitments(db=db)
        assert len(all_commitments) == 1


def test_receivable_created_on_shipment():
    with database() as db:
        product = make_product(db, "P01", stock=10)
        order = make_order(db, product, 10)
        rebalance_product_reservations(db, {product.id})
        _ship_order(db, order.id, {order.items[0].id: 5})
        receivables = db.scalars(select(Receivable)).all()
        assert len(receivables) == 1
        assert receivables[0].amount == 50
        assert receivables[0].customer_name == "客户甲"
        assert receivables[0].status == "OPEN"


def test_payment_allocation_settles_receivable():
    with database() as db:
        product = make_product(db, "P01", stock=10)
        order = make_order(db, product, 10)
        rebalance_product_reservations(db, {product.id})
        _ship_order(db, order.id, {order.items[0].id: 5})
        receivable = db.scalars(select(Receivable)).first()
        payment = create_payment(
            PaymentPayload(customer_name="客户甲", amount=50, payment_date=date(2026, 8, 23)),
            db,
        )
        result = allocate_payment(
            payment["id"],
            PaymentAllocationPayload(receivable_id=receivable.id, amount=50),
            db,
        )
        assert result["allocated_amount"] == 50
        db.refresh(receivable)
        assert receivable.status == "SETTLED"


def test_payment_allocation_rejects_over_allocation():
    with database() as db:
        product = make_product(db, "P01", stock=10)
        order = make_order(db, product, 10)
        rebalance_product_reservations(db, {product.id})
        _ship_order(db, order.id, {order.items[0].id: 5})
        receivable = db.scalars(select(Receivable)).first()
        payment = create_payment(
            PaymentPayload(customer_name="客户甲", amount=30, payment_date=date(2026, 8, 23)),
            db,
        )
        with pytest.raises(HTTPException) as error:
            allocate_payment(
                payment["id"],
                PaymentAllocationPayload(receivable_id=receivable.id, amount=40),
                db,
            )
        assert error.value.status_code == 409


def test_password_hashing_and_verification():
    password = "test123456"
    hashed = hash_password(password)
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password(password, "")


def test_user_crud_lifecycle():
    with database() as db:
        req = _admin_request()
        user = create_user(
            UserPayload(username="operator1", password="pass123", display_name="操作员", role="OPERATOR"),
            req,
            db,
        )
        assert user["username"] == "operator1"
        assert user["role"] == "OPERATOR"

        update_user(user["id"], UserUpdatePayload(display_name="高级操作员", role="ADMIN"), req, db)
        users = [u for u in db.scalars(select(User)).all()]
        assert users[0].display_name == "高级操作员"
        assert users[0].role == "ADMIN"

        delete_user(user["id"], req, db)
        db.expire_all()
        assert not db.get(User, user["id"]).active


def test_stock_reconciliation_adjusts_discrepancies():
    with database() as db:
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=10)
        db.add(part)
        db.flush()
        result = reconcile_stock(
            StockReconciliationPayload(
                items=[StockReconciliationLinePayload(item_id=part.id, physical_count=8)],
                notes="盘点差异",
            ),
            db,
        )
        assert result["discrepancy_count"] == 1
        assert result["discrepancies"][0]["difference"] == -2
        assert part.stock_qty == 8
        assert result["transaction_id"] is not None


def test_stock_reconciliation_no_discrepancy_no_transaction():
    with database() as db:
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=10)
        db.add(part)
        db.flush()
        result = reconcile_stock(
            StockReconciliationPayload(
                items=[StockReconciliationLinePayload(item_id=part.id, physical_count=10)],
            ),
            db,
        )
        assert result["discrepancy_count"] == 0
        assert result["transaction_id"] is None


def test_production_termination_returns_unproduced_materials():
    with database() as db:
        from app.main import update_production_run_status
        from app.schemas import ProductionRunStatusPayload
        db.add(ProductionSetting(id=1, line_count=1))
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=1000)
        product = make_product(db, "P01")
        db.add(part)
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=2))
        order = make_order(db, product, 100)
        recalculate_production_plan(db, NOW)
        run = db.query(ProductionRun).filter_by(status="PLANNED").one()
        update_production_run_status(
            run.id,
            ProductionRunStatusPayload(status="RUNNING"),
            db,
        )
        assert part.stock_qty == 800
        result = update_production_run_status(
            run.id,
            ProductionRunStatusPayload(
                status="TERMINATED",
                qualified_quantity=50,
                scrap_quantity=10,
                termination_reason="设备故障",
            ),
            db,
        )
        assert result["status"] == "TERMINATED"
        assert part.stock_qty == 800 + 80
        assert product.stock_qty == 50


def test_stock_transaction_reversal_restores_inventory():
    with database() as db:
        from app.main import reverse_stock_transaction
        from app.services import create_transaction
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=100)
        db.add(part)
        db.flush()
        tx = create_transaction(db, "MANUAL_OUT", [(part, -20, 5)], "出库20")
        db.commit()
        assert part.stock_qty == 80
        reversal = reverse_stock_transaction(tx.id, db)
        assert reversal["transaction_type"] == "REVERSAL"
        assert part.stock_qty == 100


def test_replenishment_run_rejects_schedule_unlock():
    with database() as db:
        from app.main import unlock_production_run_schedule
        db.add(ProductionSetting(id=1, line_count=1))
        product = make_product(db, "P01")
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=1000)
        db.add(part)
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=1))
        run = ProductionRun(
            run_no="PR001", product_id=product.id, line_slot=1, mold_slot=1,
            planned_quantity=10, produced_quantity=0,
            planned_start_at=NOW, planned_end_at=datetime(2026, 8, 22, 10),
            effective_daily_capacity=100, schedule_locked=True,
            source_type="REPLENISHMENT", status="PLANNED",
        )
        db.add(run)
        db.commit()
        with pytest.raises(HTTPException) as error:
            unlock_production_run_schedule(run.id, db)
        assert error.value.status_code == 409


def test_production_transaction_reversal_rejected():
    with database() as db:
        from app.main import reverse_stock_transaction
        from app.services import create_transaction
        product = make_product(db, "P01", stock=10)
        db.flush()
        tx = create_transaction(db, "ASSEMBLY_IN", [(product, 5, 10)], "生产入库")
        db.commit()
        with pytest.raises(HTTPException) as error:
            reverse_stock_transaction(tx.id, db)
        assert error.value.status_code == 409


def test_sale_out_reversal_cancels_receivable():
    with database() as db:
        from app.main import reverse_stock_transaction
        product = make_product(db, "P01", stock=100)
        db.flush()
        order = make_order(db, product, 10)
        db.flush()
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, {order.items[0].id: 10})
        db.commit()
        receivable = db.scalars(select(Receivable)).first()
        assert receivable is not None
        assert receivable.status == "OPEN"
        assert receivable.related_stock_transaction_id is not None
        tx = db.get(StockTransaction, receivable.related_stock_transaction_id)
        reverse_stock_transaction(tx.id, db)
        db.commit()
        db.refresh(receivable)
        assert receivable.status == "CANCELLED"


def test_replace_return_creates_replacement_pending():
    with database() as db:
        from app.main import create_order_return
        from app.schemas import OrderReturnPayload, OrderReturnLinePayload
        product = make_product(db, "P01", stock=100)
        db.flush()
        order = make_order(db, product, 10)
        db.flush()
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, {order.items[0].id: 10})
        db.commit()
        result = create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=order.items[0].id, quantity=3, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        db.refresh(order)
        assert int(order.items[0].replacement_pending_quantity or 0) == 3


def test_jwt_token_creation_and_verification():
    from app.auth import create_access_token, verify_token
    token = create_access_token(42, "testuser", "OPERATOR", "测试员")
    payload = verify_token(token)
    assert payload["sub"] == "42"
    assert payload["username"] == "testuser"
    assert payload["role"] == "OPERATOR"
    assert payload["display_name"] == "测试员"


def test_jwt_token_invalid_rejected():
    from app.auth import verify_token
    with pytest.raises(HTTPException) as error:
        verify_token("invalid.token.here")
    assert error.value.status_code == 401


def test_consume_bom_backdoor_rejected():
    with database() as db:
        from app.main import inbound
        from app.schemas import StockPayload
        product = make_product(db, "P01", stock=0)
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=100)
        db.add(part)
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=2))
        db.commit()
        with pytest.raises(HTTPException) as error:
            inbound(StockPayload(item_id=product.id, quantity=5, consume_bom=True), db)
        assert error.value.status_code == 410


def test_bom_based_cost_on_completion():
    with database() as db:
        from app.main import complete_production_run
        from app.schemas import ProductionCompletionPayload
        product = make_product(db, "P01", stock=0)
        part = InventoryItem(sku="X", name="零件X", kind="PART", stock_qty=1000, cost_price=5)
        db.add(part)
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=2))
        db.add(ProductionSetting(id=1, line_count=1))
        run = ProductionRun(
            run_no="PR001", product_id=product.id, line_slot=1, mold_slot=1,
            planned_quantity=10, produced_quantity=0,
            planned_start_at=NOW, planned_end_at=datetime(2026, 8, 22, 10),
            effective_daily_capacity=100, status="RUNNING",
            actual_start_at=NOW, workflow_version=2,
        )
        db.add(run)
        db.commit()
        result = complete_production_run(
            run.id,
            ProductionCompletionPayload(qualified_quantity=8, scrap_quantity=2),
            db,
        )
        db.commit()
        expected_cost = (2 * 5 * 10) / 8
        assert abs(float(product.cost_price) - expected_cost) < 0.01
