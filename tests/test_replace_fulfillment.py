"""REPLACE 换货闭环端到端测试。

覆盖交接要求的完整场景：
订单 100 → 出 100 → REPLACE 退 10 → pending 10 → 库存 5 → 预留 5
→ 再补 5（生产/入库）→ 预留 10 → 补发 10 → pending 归零 → 订单重新 FULFILLED；
以及混合出库拆分、SALE_OUT 冲销按履约来源恢复、退货上限含换货补发。
"""
from datetime import date
from pathlib import Path
import sys

from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import (
    _ship_order,
    create_order_return,
    reverse_stock_transaction,
)
from app.models import (
    InventoryItem,
    OrderShipmentAllocation,
    Receivable,
    SalesOrder,
    SalesOrderItem,
    StockTransaction,
)
from app.planning import recalculate_production_plan
from app.schemas import OrderReturnLinePayload, OrderReturnPayload
from app.services import create_transaction, rebalance_product_reservations


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_product(db: Session, sku: str = "P01", stock: int = 0, price: float = 10) -> InventoryItem:
    row = InventoryItem(
        sku=sku, name=sku, kind="PRODUCT", stock_qty=stock,
        daily_capacity=100, mold_count=1, sale_price=price,
    )
    db.add(row)
    db.flush()
    return row


def make_order(db: Session, product: InventoryItem, quantity: int = 100) -> SalesOrder:
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


def inbound(db: Session, product: InventoryItem, quantity: int) -> None:
    create_transaction(db, "GENERAL_IN", [(product, quantity, 10)], "测试补货")
    rebalance_product_reservations(db, {product.id})
    recalculate_production_plan(db)
    db.commit()


def line_of(db: Session, order_id: int) -> SalesOrderItem:
    return db.scalar(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id))


def test_replacement_end_to_end_closure():
    """交接指定的完整闭环：100 → 出 100 → 换 10 → 补发 10 → 归零 → FULFILLED。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()

        # 1. 原单全部出库 → FULFILLED
        first = _ship_order(db, order.id, None)
        db.refresh(order)
        line = order.items[0]
        assert int(line.shipped_quantity) == 100
        assert order.status == "FULFILLED"
        assert float(product.stock_qty) == 0
        receivables = db.scalars(select(Receivable).where(Receivable.order_id == order.id)).all()
        assert len(receivables) == 1 and float(receivables[0].amount) == 1000

        # 2. 客户退 10 要求换货（不回库）
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=10, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        db.refresh(order); db.refresh(line)
        assert int(line.replacement_pending_quantity) == 10
        # 换货未补齐前订单必须退出 FULFILLED，否则补发出库会被状态检查拒绝
        assert order.status == "PARTIALLY_SHIPPED"

        # 3. 库存只有 5 → 预留 5，生产缺口 5
        inbound(db, product, 5)
        db.refresh(line)
        assert int(line.reserved_quantity) == 5
        assert int(line.production_required_quantity) == 5

        # 4. 再补 5（完工入库等价）→ 预留 10，缺口 0；已发生过出库的订单状态为 PARTIALLY_SHIPPED
        inbound(db, product, 5)
        db.refresh(line); db.refresh(order)
        assert int(line.reserved_quantity) == 10
        assert int(line.production_required_quantity) == 0
        assert order.status == "PARTIALLY_SHIPPED"

        # 5. 补发 10：全部记为换货履约，pending 归零，shipped 保持 100
        second = _ship_order(db, order.id, None)
        db.refresh(order); db.refresh(line)
        assert int(line.shipped_quantity) == 100
        assert int(line.replacement_pending_quantity) == 0
        assert int(line.replacement_shipped_quantity) == 10
        assert order.status == "FULFILLED"
        assert float(product.stock_qty) == 0

        # 换货补发不产生新应收（货款在原出库时已确认）
        receivables = db.scalars(select(Receivable).where(Receivable.order_id == order.id)).all()
        assert len(receivables) == 1
        allocations = db.scalars(
            select(OrderShipmentAllocation).where(
                OrderShipmentAllocation.stock_transaction_id == second["transaction_id"]
            )
        ).all()
        assert [(a.fulfillment_type, a.quantity) for a in allocations] == [("REPLACEMENT", 10)]


def test_reversal_of_replacement_shipment_restores_pending():
    """冲销换货补发出库：恢复 replacement_pending，不动 shipped_quantity。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, None)
        line = order.items[0]
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=10, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        inbound(db, product, 10)
        replacement = _ship_order(db, order.id, None)
        db.refresh(line)
        assert int(line.replacement_pending_quantity) == 0

        reverse_stock_transaction(replacement["transaction_id"], db)
        db.refresh(line); db.refresh(order)
        assert int(line.replacement_pending_quantity) == 10
        assert int(line.replacement_shipped_quantity) == 0
        assert int(line.shipped_quantity) == 100
        assert order.status == "PARTIALLY_SHIPPED"
        # 库存随之恢复 10
        assert float(product.stock_qty) == 10
        # 换货出库没有应收，冲销不应触碰应收
        receivables = db.scalars(select(Receivable).where(Receivable.order_id == order.id)).all()
        assert len(receivables) == 1 and receivables[0].status == "OPEN"


def test_reversal_of_original_shipment_restores_shipped():
    """冲销原单出库：按 ORIGINAL 分配恢复 shipped_quantity。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        first = _ship_order(db, order.id, None)
        line = order.items[0]
        assert int(line.shipped_quantity) == 100

        reverse_stock_transaction(first["transaction_id"], db)
        db.refresh(line); db.refresh(order)
        assert int(line.shipped_quantity) == 0
        assert float(product.stock_qty) == 100
        receivables = db.scalars(select(Receivable).where(Receivable.order_id == order.id)).all()
        assert receivables[0].status == "CANCELLED"


def test_mixed_shipment_splits_original_then_replacement():
    """一次出库跨越原单剩余与换货：先满足原单，其余记换货。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, {order.items[0].id: 30})
        line = order.items[0]
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=5, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        # 有效需求 = 原单剩余 70 + 换货 5 = 75
        inbound(db, product, 75)
        db.refresh(line)
        assert int(line.reserved_quantity) == 75

        mixed = _ship_order(db, order.id, {line.id: 75})
        db.refresh(order); db.refresh(line)
        assert int(line.shipped_quantity) == 100
        assert int(line.replacement_pending_quantity) == 0
        assert int(line.replacement_shipped_quantity) == 5
        assert order.status == "FULFILLED"
        allocations = db.scalars(
            select(OrderShipmentAllocation).where(
                OrderShipmentAllocation.stock_transaction_id == mixed["transaction_id"]
            )
        ).all()
        assert sorted((a.fulfillment_type, a.quantity) for a in allocations) == [
            ("ORIGINAL", 70), ("REPLACEMENT", 5),
        ]
        # 应收只按原单 70 计价
        receivable = db.scalar(
            select(Receivable).where(Receivable.related_stock_transaction_id == mixed["transaction_id"])
        )
        assert receivable is not None and float(receivable.amount) == 700


def test_ship_cannot_exceed_effective_remaining():
    """出库上限 = 原单剩余 + 待补换货；换货补发不再是物理上不可能的操作。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, None)
        line = order.items[0]
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=10, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        inbound(db, product, 10)
        # 超过有效剩余 10 被拒绝
        try:
            _ship_order(db, order.id, {line.id: 11})
            raise AssertionError("超出有效剩余的出库应当被拒绝")
        except HTTPException as error:
            assert error.status_code == 409
        # 正好 10（全部换货）可以
        _ship_order(db, order.id, {line.id: 10})
        db.refresh(line)
        assert int(line.replacement_pending_quantity) == 0


def test_returnable_includes_replacement_shipped():
    """退货上限计入换货补发数量：客户手里的货 = 原单 + 换货 - 已退。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, None)
        line = order.items[0]
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=5, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        inbound(db, product, 5)
        _ship_order(db, order.id, None)
        db.refresh(line)
        # shipped=100 + replacement_shipped=5 - returned=5 = 100 件在客户手里
        assert int(line.returned_quantity) == 5
        assert int(line.replacement_shipped_quantity) == 5
        # 再退 100（含换货件）应被接受；超出则拒绝
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=100, restock=False)],
                resolution="REFUND",
            ),
            db,
        )
        db.refresh(line)
        assert int(line.returned_quantity) == 105
        try:
            create_order_return(
                order.id,
                OrderReturnPayload(
                    items=[OrderReturnLinePayload(order_item_id=line.id, quantity=1, restock=False)],
                    resolution="REFUND",
                ),
                db,
            )
            raise AssertionError("超出可退数量应当被拒绝")
        except HTTPException as error:
            assert error.status_code == 409


def test_sale_out_reversal_blocked_when_returns_exist():
    """已发生退货的出库不能直接冲销：否则已退数量会超过累计发货。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        shipment = _ship_order(db, order.id, None)
        line = order.items[0]
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=10, restock=False)],
                resolution="REFUND",
            ),
            db,
        )
        try:
            reverse_stock_transaction(shipment["transaction_id"], db)
            raise AssertionError("已发生退货的出库应当拒绝冲销")
        except HTTPException as error:
            assert error.status_code == 409
            assert "退货" in error.detail
        # 冲销被拒后，账面与库存保持原样
        db.refresh(line)
        assert int(line.shipped_quantity) == 100
        assert float(product.stock_qty) == 0


def test_sale_out_reversal_allowed_when_returns_still_covered():
    """多张出库单场景：冲销后累计发货仍不低于已退数量时允许。"""
    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, {order.items[0].id: 60})
        second = _ship_order(db, order.id, {order.items[0].id: 40})
        line = order.items[0]
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=10, restock=False)],
                resolution="REFUND",
            ),
            db,
        )
        reverse_stock_transaction(second["transaction_id"], db)
        db.refresh(line)
        assert int(line.shipped_quantity) == 60
        assert int(line.returned_quantity) == 10
        assert float(product.stock_qty) == 40


def test_shipment_snapshot_amount_counts_original_only():
    """单据金额快照只按原单履约计价；换货数量单独暴露给单据/打印。"""
    from sqlalchemy.orm import selectinload

    from app.services import transaction_dict

    def load_tx(db: Session, tx_id: int) -> StockTransaction:
        return db.scalar(
            select(StockTransaction)
            .where(StockTransaction.id == tx_id)
            .options(selectinload(StockTransaction.shipment_allocations).selectinload(OrderShipmentAllocation.order_item))
        )

    with database() as db:
        product = make_product(db, stock=100)
        order = make_order(db, product, 100)
        rebalance_product_reservations(db, {product.id})
        db.commit()
        _ship_order(db, order.id, {order.items[0].id: 30})
        line = order.items[0]
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=5, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        inbound(db, product, 75)

        # 混合出库：70 原单 + 5 换货 → 金额快照只算 70 的
        mixed = _ship_order(db, order.id, {line.id: 75})
        tx = load_tx(db, mixed["transaction_id"])
        tx_line = tx.lines[0]
        assert float(tx_line.line_total_snapshot) == 700
        data = transaction_dict(tx)
        assert data["lines"][0]["replacement_quantity"] == 5

        # 纯换货补发：金额 0，换货数量完整暴露
        create_order_return(
            order.id,
            OrderReturnPayload(
                items=[OrderReturnLinePayload(order_item_id=line.id, quantity=10, restock=False)],
                resolution="REPLACE",
            ),
            db,
        )
        inbound(db, product, 10)
        pure = _ship_order(db, order.id, None)
        tx2 = load_tx(db, pure["transaction_id"])
        assert float(tx2.lines[0].line_total_snapshot) == 0
        data2 = transaction_dict(tx2)
        assert data2["lines"][0]["replacement_quantity"] == 10
