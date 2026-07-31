from datetime import date, datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .models import InventoryItem, ProductBomItem, SalesOrder, SalesOrderItem, StockTransaction, StockTransactionItem


def serial(prefix: str) -> str:
    return f"{prefix}{datetime.now():%Y%m%d%H%M%S}{uuid4().hex[:4].upper()}"


def ensure_sku_available(db: Session, sku: str, exclude_id: int | None = None) -> None:
    query = select(InventoryItem).where(InventoryItem.sku == sku.strip().upper())
    if exclude_id:
        query = query.where(InventoryItem.id != exclude_id)
    if db.scalar(query):
        raise HTTPException(409, "物料编码已存在")


def item_dict(item: InventoryItem, include_bom: bool = False) -> dict:
    data = {
        "id": item.id,
        "sku": item.sku,
        "name": item.name,
        "kind": item.kind,
        "unit": item.unit,
        "spec": item.spec,
        "cost_price": item.cost_price,
        "sale_price": item.sale_price,
        "min_stock": item.min_stock,
        "stock_qty": item.stock_qty,
        "active": item.active,
        "low_stock": item.stock_qty <= item.min_stock,
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
    }
    if include_bom:
        data["components"] = [
            {
                "id": line.id,
                "part_id": line.part_id,
                "part_sku": line.part.sku,
                "part_name": line.part.name,
                "unit": line.part.unit,
                "quantity": line.quantity,
                "available_stock": line.part.stock_qty,
            }
            for line in item.bom_components
        ]
    return data


def order_dict(order: SalesOrder) -> dict:
    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_name": order.customer_name,
        "customer_phone": order.customer_phone,
        "customer_address": order.customer_address,
        "status": order.status,
        "order_date": order.order_date.isoformat(),
        "total_amount": order.total_amount,
        "notes": order.notes,
        "created_at": order.created_at.isoformat(),
        "items": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "product_sku": line.product.sku,
                "product_name": line.product.name,
                "quantity": line.quantity,
                "unit_price": line.unit_price,
                "line_total": line.line_total,
            }
            for line in order.items
        ],
    }


def transaction_dict(tx: StockTransaction) -> dict:
    return {
        "id": tx.id,
        "transaction_no": tx.transaction_no,
        "transaction_type": tx.transaction_type,
        "occurred_at": tx.occurred_at.isoformat(),
        "related_order_id": tx.related_order_id,
        "related_order_no": tx.related_order.order_no if tx.related_order else None,
        "notes": tx.notes,
        "lines": [
            {
                "id": line.id,
                "item_id": line.item_id,
                "sku": line.item.sku,
                "name": line.item.name,
                "kind": line.item.kind,
                "unit": line.item.unit,
                "quantity_change": line.quantity_change,
                "unit_cost": line.unit_cost,
            }
            for line in tx.lines
        ],
    }


def create_transaction(
    db: Session,
    tx_type: str,
    changes: list[tuple[InventoryItem, float, float]],
    notes: str = "",
    related_order_id: int | None = None,
) -> StockTransaction:
    for item, delta, _unit_cost in changes:
        if item.stock_qty + delta < -1e-9:
            raise HTTPException(409, f"{item.name} 库存不足，当前 {item.stock_qty:g} {item.unit}")

    tx = StockTransaction(
        transaction_no=serial("ST"), transaction_type=tx_type, notes=notes.strip(), related_order_id=related_order_id
    )
    db.add(tx)
    db.flush()
    for item, delta, unit_cost in changes:
        item.stock_qty = round(item.stock_qty + delta, 6)
        if delta > 0 and unit_cost > 0:
            item.cost_price = unit_cost
        db.add(StockTransactionItem(transaction_id=tx.id, item_id=item.id, quantity_change=delta, unit_cost=unit_cost))
    db.flush()
    return tx


def load_order(db: Session, order_id: int) -> SalesOrder:
    order = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == order_id)
        .options(selectinload(SalesOrder.items).selectinload(SalesOrderItem.product))
    )
    if not order:
        raise HTTPException(404, "客单不存在")
    return order


def seed_demo(db: Session) -> None:
    if db.scalar(select(InventoryItem.id).limit(1)):
        return

    parts = [
        InventoryItem(sku="P-AL-001", name="铝合金外壳", kind="PART", unit="个", spec="120×80×35mm", cost_price=18.5, min_stock=30),
        InventoryItem(sku="P-PCB-002", name="控制主板", kind="PART", unit="块", spec="V2.1 / 24V", cost_price=68, min_stock=20),
        InventoryItem(sku="P-SCR-003", name="M3 固定螺丝", kind="PART", unit="颗", spec="M3×8", cost_price=0.12, min_stock=200),
        InventoryItem(sku="P-CAB-004", name="电源连接线", kind="PART", unit="根", spec="1.5m", cost_price=6.8, min_stock=40),
    ]
    products = [
        InventoryItem(sku="FG-CTRL-A", name="智能控制器 A", kind="PRODUCT", unit="台", spec="标准版", cost_price=96, sale_price=239, min_stock=8),
        InventoryItem(sku="FG-CTRL-P", name="智能控制器 Pro", kind="PRODUCT", unit="台", spec="增强版", cost_price=128, sale_price=329, min_stock=5),
    ]
    db.add_all(parts + products)
    db.flush()

    db.add_all([
        ProductBomItem(product_id=products[0].id, part_id=parts[0].id, quantity=1),
        ProductBomItem(product_id=products[0].id, part_id=parts[1].id, quantity=1),
        ProductBomItem(product_id=products[0].id, part_id=parts[2].id, quantity=4),
        ProductBomItem(product_id=products[1].id, part_id=parts[0].id, quantity=1),
        ProductBomItem(product_id=products[1].id, part_id=parts[1].id, quantity=1),
        ProductBomItem(product_id=products[1].id, part_id=parts[2].id, quantity=6),
        ProductBomItem(product_id=products[1].id, part_id=parts[3].id, quantity=1),
    ])
    create_transaction(
        db,
        "OPENING",
        [(parts[0], 120, parts[0].cost_price), (parts[1], 75, parts[1].cost_price), (parts[2], 600, parts[2].cost_price),
         (parts[3], 90, parts[3].cost_price), (products[0], 16, products[0].cost_price), (products[1], 8, products[1].cost_price)],
        "系统演示期初库存",
    )
    order = SalesOrder(
        order_no=serial("SO"), customer_name="上海示例科技", customer_phone="021-5555 0188",
        customer_address="上海市浦东新区", status="CONFIRMED", order_date=date.today(), notes="演示客单"
    )
    order.items = [SalesOrderItem(product_id=products[0].id, quantity=3, unit_price=239, line_total=717)]
    order.total_amount = 717
    db.add(order)
    db.commit()

