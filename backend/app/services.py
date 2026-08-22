from datetime import date, datetime
import hashlib
import logging
import secrets
from uuid import uuid4

from fastapi import HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    InventoryItem,
    OperationLog,
    OrderShipmentAllocation,
    ProductBomItem,
    SalesOrder,
    SalesOrderItem,
    StockReservation,
    StockTransaction,
    StockTransactionItem,
)


_logger = logging.getLogger("uvicorn.error")


def client_ip(request: Request) -> str:
    """从请求中解析客户端 IP 地址。优先使用反向代理头，最后回退到连接地址。"""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    real_ip = request.headers.get("x-real-ip")
    if real_ip:
        return real_ip.strip()
    return request.client.host if request.client else "unknown"


def record_operation(
    db: Session,
    *,
    request: Request,
    username: str = "",
    action: str = "",
    target: str = "",
    status: str = "SUCCESS",
    detail: str = "",
) -> None:
    """记录一条操作日志。日志写入失败不会影响业务流程。"""
    try:
        db.add(OperationLog(
            username=(username or "").strip()[:120],
            action=(action or "").strip()[:60],
            target=(target or "").strip()[:255],
            method=request.method,
            path=request.url.path[:255],
            ip_address=client_ip(request)[:64],
            status=(status or "SUCCESS").strip()[:20],
            detail=(detail or "")[:2000],
        ))
        db.commit()
    except Exception as error:  # noqa: BLE001 - 日志失败不应中断业务
        try:
            db.rollback()
        except Exception:
            pass
        _logger.warning("记录操作日志失败: %s", error)


def operation_log_dict(log: OperationLog) -> dict:
    return {
        "id": log.id,
        "username": log.username,
        "action": log.action,
        "target": log.target,
        "method": log.method,
        "path": log.path,
        "ip_address": log.ip_address,
        "status": log.status,
        "detail": log.detail,
        "business_summary": log.business_summary or "",
        "created_at": log.created_at.isoformat(),
    }


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    hash_value = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}${hash_value.hex()}"


def verify_password(password: str, stored: str) -> bool:
    if not stored or "$" not in stored:
        return False
    salt, expected_hash = stored.split("$", 1)
    hash_value = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return secrets.compare_digest(hash_value.hex(), expected_hash)


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
        "daily_capacity": item.daily_capacity,
        "mold_count": max(int(item.mold_count or 0), 1) if item.kind == "PRODUCT" else 0,
        "stock_qty": item.stock_qty,
        "semi_finished_qty": int(item.semi_finished_qty or 0),
        "processing_qty": int(item.processing_qty or 0),
        "requires_external_processing": bool(item.requires_external_processing),
        "external_process_name": item.external_process_name or "",
        "default_external_lead_days": int(item.default_external_lead_days or 0),
        "sample_stock_qty": item.sample_stock_qty,
        "supply_mode": item.supply_mode if item.kind == "PART" else "STOCK",
        "active": item.active,
        "low_stock": item.stock_qty < item.min_stock,
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
        "required_date": (order.required_date or order.order_date).isoformat(),
        "total_amount": order.total_amount,
        "estimated_completion_at": (
            order.estimated_completion_at.isoformat() if order.estimated_completion_at else None
        ),
        "eta_calculated_at": order.eta_calculated_at.isoformat() if order.eta_calculated_at else None,
        "eta_reliable": order.eta_reliable,
        "eta_note": order.eta_note,
        "notes": order.notes,
        "created_at": order.created_at.isoformat(),
        "items": [
            {
                "id": line.id,
                "product_id": line.product_id,
                "product_sku": line.product.sku,
                "product_name": line.product.name,
                "quantity": line.quantity,
                "shipped_quantity": int(line.shipped_quantity or 0),
                "returned_quantity": int(line.returned_quantity or 0),
                "replacement_pending_quantity": int(line.replacement_pending_quantity or 0),
                "replacement_shipped_quantity": int(line.replacement_shipped_quantity or 0),
                "returnable_quantity": max(
                    int(line.shipped_quantity or 0)
                    + int(line.replacement_shipped_quantity or 0)
                    - int(line.returned_quantity or 0),
                    0,
                ),
                "remaining_quantity": max(
                    int(line.quantity) - int(line.shipped_quantity or 0)
                    + int(line.replacement_pending_quantity or 0),
                    0,
                ),
                "reserved_quantity": line.reserved_quantity or 0,
                "pipeline_quantity": int(line.pipeline_quantity or 0),
                "reference_price": line.reference_price,
                "unit_price": line.unit_price,
                "line_total": line.line_total,
                "production_required_quantity": line.production_required_quantity or 0,
                "estimated_completion_at": (
                    line.estimated_completion_at.isoformat() if line.estimated_completion_at else None
                ),
                "eta_reliable": line.eta_reliable,
                "eta_note": line.eta_note,
                "discount_rate": round((line.unit_price / line.reference_price * 100) if line.reference_price else 100, 2),
                "discount_amount": round(max(line.reference_price - line.unit_price, 0) * line.quantity, 2),
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
        "related_order_no": tx.order_no_snapshot or (tx.related_order.order_no if tx.related_order else None),
        "related_production_run_id": tx.related_production_run_id,
        "related_production_run_no": (
            tx.related_production_run.run_no if tx.related_production_run else None
        ),
        "counterparty_name": tx.counterparty_name_snapshot or (
            tx.related_order.customer_name if tx.related_order else None
        ),
        "counterparty_phone": tx.counterparty_phone_snapshot or (
            tx.related_order.customer_phone if tx.related_order else None
        ),
        "counterparty_address": tx.counterparty_address_snapshot or (
            tx.related_order.customer_address if tx.related_order else None
        ),
        "operator": tx.operator_snapshot,
        "notes": tx.notes,
        "status": tx.status or "POSTED",
        "reversal_of_transaction_id": tx.reversal_of_transaction_id,
        "reversed_by_transaction_id": tx.reversed_by_transaction_id,
        "lines": [
            {
                "id": line.id,
                "item_id": line.item_id,
                "sku": line.sku_snapshot or line.item.sku,
                "name": line.name_snapshot or line.item.name,
                "spec": line.spec_snapshot if line.spec_snapshot is not None else line.item.spec,
                "kind": line.item.kind,
                "unit": line.unit_snapshot or line.item.unit,
                "inventory_scope": (
                    "SAMPLE" if tx.transaction_type == "SAMPLE_ADJUST" else line.item.kind
                ),
                "quantity_change": line.quantity_change,
                "unit_cost": line.unit_cost,
                "unit_price": line.unit_price_snapshot,
                "line_total": line.line_total_snapshot,
                "inventory_bucket": line.inventory_bucket or "FINISHED",
                "affects_primary_stock": bool(line.affects_primary_stock),
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
    related_production_run_id: int | None = None,
    occurred_at: datetime | None = None,
    operator: str | None = None,
    price_snapshots: dict[int, tuple[float, float]] | None = None,
    counterparty_name: str | None = None,
    counterparty_phone: str | None = None,
    counterparty_address: str | None = None,
    apply_inventory: bool = True,
) -> StockTransaction:
    if not changes:
        raise HTTPException(400, "库存流水至少需要一项物料变化")

    change_map: dict[int, list] = {}
    for item, delta, unit_cost in changes:
        if abs(float(delta)) <= 1e-9:
            continue
        entry = change_map.setdefault(item.id, [item, 0.0, float(unit_cost)])
        entry[1] += float(delta)
        if delta > 0 and unit_cost > 0:
            entry[2] = float(unit_cost)
    change_map = {
        item_id: entry for item_id, entry in change_map.items()
        if abs(entry[1]) > 1e-9
    }
    if not change_map:
        raise HTTPException(400, "库存变化不能全部为零")

    # 对同一笔流水涉及的物料按固定顺序加行锁，避免局域网内多个用户并发
    # 出入库时发生丢失更新或把库存扣成负数。SQLite 测试环境不支持 FOR UPDATE。
    db.flush()
    db.expire_all()
    locked_items = {
        item.id: item
        for item in db.scalars(
            select(InventoryItem)
            .where(InventoryItem.id.in_(sorted(change_map)))
            .order_by(InventoryItem.id)
            .with_for_update()
        ).all()
    } if db.bind and db.bind.dialect.name != "sqlite" else {
        item_id: entry[0] for item_id, entry in change_map.items()
    }
    if len(locked_items) != len(change_map):
        raise HTTPException(409, "库存物料已被停用或删除，请刷新后重试")

    normalized_changes = [
        (locked_items[item_id], round(entry[1], 6), entry[2])
        for item_id, entry in sorted(change_map.items())
    ]
    for item, delta, _unit_cost in normalized_changes:
        if apply_inventory and item.stock_qty + delta < -1e-9:
            raise HTTPException(409, f"{item.name} 库存不足，当前 {item.stock_qty:g} {item.unit}")

    related_order = db.get(SalesOrder, related_order_id) if related_order_id else None
    tx = StockTransaction(
        transaction_no=serial("ST"),
        transaction_type=tx_type,
        notes=notes.strip(),
        related_order_id=related_order_id,
        related_production_run_id=related_production_run_id,
        occurred_at=occurred_at or datetime.now(),
        order_no_snapshot=related_order.order_no if related_order else None,
        counterparty_name_snapshot=(
            counterparty_name.strip()
            if counterparty_name is not None
            else (related_order.customer_name if related_order else None)
        ),
        counterparty_phone_snapshot=(
            counterparty_phone.strip()
            if counterparty_phone is not None
            else (related_order.customer_phone if related_order else None)
        ),
        counterparty_address_snapshot=(
            counterparty_address.strip()
            if counterparty_address is not None
            else (related_order.customer_address if related_order else None)
        ),
        operator_snapshot=operator,
    )
    db.add(tx)
    db.flush()
    for item, delta, unit_cost in normalized_changes:
        if apply_inventory:
            if delta > 0 and unit_cost > 0:
                old_stock = float(item.stock_qty)
                old_value = old_stock * float(item.cost_price)
                new_value = old_value + float(delta) * float(unit_cost)
                new_stock = old_stock + float(delta)
                item.stock_qty = round(new_stock, 6)
                if new_stock > 1e-9:
                    item.cost_price = round(new_value / new_stock, 2)
            else:
                item.stock_qty = round(item.stock_qty + delta, 6)
        price, line_total = (price_snapshots or {}).get(item.id, (None, None))
        bucket = _infer_inventory_bucket(tx_type, item.kind)
        db.add(StockTransactionItem(
            transaction_id=tx.id,
            item_id=item.id,
            quantity_change=delta,
            unit_cost=unit_cost,
            sku_snapshot=item.sku,
            name_snapshot=item.name,
            spec_snapshot=item.spec,
            unit_snapshot=item.unit,
            unit_price_snapshot=price,
            line_total_snapshot=line_total,
            inventory_bucket=bucket,
            affects_primary_stock=apply_inventory,
        ))
    db.flush()
    return tx


def load_order(db: Session, order_id: int) -> SalesOrder:
    order = db.scalar(
        select(SalesOrder)
        .where(SalesOrder.id == order_id)
        .options(
            selectinload(SalesOrder.items)
            .selectinload(SalesOrderItem.product)
            .selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part)
        )
    )
    if not order:
        raise HTTPException(404, "客单不存在")
    return order


RESERVATION_STATUSES = (
    "CONFIRMED",
    "WAITING_MATERIALS",
    "READY_TO_SHIP",
    "PARTIALLY_SHIPPED",
)


def effective_line_demand(line: SalesOrderItem) -> int:
    """订单行的有效需求 = 原单剩余 + 待补换货。预留、排产、出库上限都用它。"""
    return (
        max(int(line.quantity) - int(line.shipped_quantity or 0), 0)
        + int(line.replacement_pending_quantity or 0)
    )


def _infer_inventory_bucket(tx_type: str, item_kind: str) -> str:
    if tx_type == "SAMPLE_ADJUST":
        return "SAMPLE"
    if tx_type in ("SEMI_FINISHED_IN",):
        return "SEMI_FINISHED"
    if tx_type in ("PROCESS_OUT",):
        return "PROCESSING"
    if tx_type in ("PRODUCTION_OUT", "PRODUCTION_RETURN", "PURCHASE_IN"):
        return "RAW"
    if tx_type in ("ASSEMBLY_IN", "SALE_OUT", "SALE_RETURN_IN", "PROCESS_RETURN_IN"):
        return "FINISHED"
    return "FINISHED" if item_kind == "PRODUCT" else "RAW"


def rebalance_product_reservations(db: Session, product_ids: set[int] | None = None) -> None:
    """按要求交期、订单日期、订单号的顺序，将现有成品库存分配给所有活动客单。"""
    if product_ids is None:
        product_ids = set(db.scalars(
            select(SalesOrderItem.product_id)
            .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
            .where(SalesOrder.status.in_(RESERVATION_STATUSES))
            .distinct()
        ).all())
    if product_ids and db.bind and db.bind.dialect.name != "sqlite":
        db.scalars(
            select(InventoryItem)
            .where(InventoryItem.id.in_(sorted(product_ids)))
            .order_by(InventoryItem.id)
            .with_for_update()
        ).all()
    query = (
        select(SalesOrderItem)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .options(selectinload(SalesOrderItem.product))
        .where(SalesOrder.status.in_(RESERVATION_STATUSES))
        .order_by(SalesOrder.required_date, SalesOrder.order_date, SalesOrder.id, SalesOrderItem.id)
    )
    if product_ids:
        query = query.where(SalesOrderItem.product_id.in_(product_ids))
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    lines = db.scalars(query).all()
    line_ids = [line.id for line in lines]
    reservations = {
        reservation.order_item_id: reservation
        for reservation in db.scalars(
            select(StockReservation).where(StockReservation.order_item_id.in_(line_ids))
        ).all()
    } if line_ids else {}
    remaining: dict[int, float] = {}
    for line in lines:
        available = remaining.setdefault(line.product_id, float(line.product.stock_qty))
        demand = effective_line_demand(line)
        reserved_quantity = int(min(demand, max(available, 0)))
        line.reserved_quantity = reserved_quantity
        reservation = reservations.get(line.id)
        if reservation is None:
            reservation = StockReservation(
                order_item_id=line.id,
                product_id=line.product_id,
            )
            db.add(reservation)
        reservation.quantity = reserved_quantity
        reservation.status = "ACTIVE" if reserved_quantity > 1e-9 else "RELEASED"
        remaining[line.product_id] = available - line.reserved_quantity
    affected_orders = {line.order_id for line in lines}
    if product_ids:
        affected_orders.update(db.scalars(
            select(SalesOrder.id)
            .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrderItem.product_id.in_(product_ids), SalesOrder.status.in_(RESERVATION_STATUSES))
        ).all())
    for order_id in affected_orders:
        active_order = db.get(SalesOrder, order_id)
        order_lines = db.scalars(select(SalesOrderItem).where(SalesOrderItem.order_id == order_id)).all()
        if active_order and active_order.status in RESERVATION_STATUSES:
            all_shipped = all(
                int(line.shipped_quantity or 0) >= int(line.quantity)
                and int(line.replacement_pending_quantity or 0) <= 0
                for line in order_lines
            )
            any_shipped = any(int(line.shipped_quantity or 0) > 0 for line in order_lines)
            all_remaining_reserved = all(
                int(line.reserved_quantity or 0) >= effective_line_demand(line)
                for line in order_lines
            )
            if all_shipped:
                active_order.status = "FULFILLED"
            elif any_shipped:
                active_order.status = "PARTIALLY_SHIPPED"
            elif all_remaining_reserved:
                active_order.status = "READY_TO_SHIP"
            else:
                active_order.status = "WAITING_MATERIALS"
    db.flush()


def reserved_product_quantity(db: Session, product_id: int, exclude_order_id: int | None = None) -> float:
    query = (
        select(func.coalesce(func.sum(StockReservation.quantity), 0))
        .join(SalesOrderItem, SalesOrderItem.id == StockReservation.order_item_id)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .where(
            StockReservation.product_id == product_id,
            StockReservation.status == "ACTIVE",
            SalesOrder.status.in_(RESERVATION_STATUSES),
        )
    )
    if exclude_order_id is not None:
        query = query.where(SalesOrderItem.order_id != exclude_order_id)
    return float(db.scalar(query) or 0)


def order_workflow_dict(db: Session, order: SalesOrder) -> dict:
    product_lines: list[dict] = []
    material_map: dict[int, dict] = {}
    missing_bom: list[dict] = []

    for line in order.items:
        remaining_quantity = effective_line_demand(line)
        reserved = min(int(line.reserved_quantity or 0), remaining_quantity)
        other_reserved = reserved_product_quantity(db, line.product_id, order.id)
        free_stock = max(float(line.product.stock_qty) - other_reserved - reserved, 0)
        pipeline_quantity = min(int(line.pipeline_quantity or 0), max(remaining_quantity - reserved, 0))
        production_required = max(remaining_quantity - reserved - pipeline_quantity, 0)
        priority_rows = db.execute(
            select(SalesOrder.id, SalesOrder.order_no, SalesOrder.required_date)
            .join(SalesOrderItem, SalesOrderItem.order_id == SalesOrder.id)
            .where(SalesOrderItem.product_id == line.product_id, SalesOrder.status.in_(RESERVATION_STATUSES))
            .order_by(SalesOrder.required_date, SalesOrder.order_date, SalesOrder.id)
        ).all()
        priority_rank = next((index + 1 for index, row in enumerate(priority_rows) if row.id == order.id), 1)
        product_lines.append({
            "order_item_id": line.id,
            "product_id": line.product_id,
            "sku": line.product.sku,
            "name": line.product.name,
            "unit": line.product.unit,
            "ordered_quantity": line.quantity,
            "shipped_quantity": int(line.shipped_quantity or 0),
            "remaining_quantity": remaining_quantity,
            "reserved_quantity": reserved,
            "current_stock": int(line.product.stock_qty or 0),
            "reserved_by_other_orders": int(other_reserved),
            "pipeline_quantity": pipeline_quantity,
            "free_stock": round(free_stock, 6),
            "production_required": round(production_required, 6),
            "bom_configured": bool(line.product.bom_components),
            "priority_rank": priority_rank,
            "priority_total": len(priority_rows),
            "waiting_for_earlier_orders": (
                priority_rank > 1
                and other_reserved > 0
                and reserved < remaining_quantity
            ),
            "estimated_completion_at": (
                line.estimated_completion_at.isoformat() if line.estimated_completion_at else None
            ),
            "eta_reliable": line.eta_reliable,
            "eta_note": line.eta_note,
        })
        if production_required <= 1e-9:
            continue
        if not line.product.bom_components:
            missing_bom.append({"product_id": line.product_id, "sku": line.product.sku, "name": line.product.name})
            continue
        for component in line.product.bom_components:
            required = float(component.quantity) * production_required
            material = material_map.setdefault(component.part_id, {
                "part_id": component.part_id,
                "sku": component.part.sku,
                "name": component.part.name,
                "unit": component.part.unit,
                "supply_mode": component.part.supply_mode or "STOCK",
                "required_quantity": 0.0,
                "available_stock": float(component.part.stock_qty),
            })
            material["required_quantity"] += required

    material_lines = []
    for material in material_map.values():
        material["required_quantity"] = round(material["required_quantity"], 6)
        material["shortage_quantity"] = round(
            max(material["required_quantity"] - material["available_stock"], 0), 6
        )
        material_lines.append(material)
    material_lines.sort(key=lambda row: (row["shortage_quantity"] <= 0, row["sku"]))

    has_shortage = any(row["shortage_quantity"] > 1e-9 for row in material_lines)
    production_required = any(row["production_required"] > 1e-9 for row in product_lines)
    ready_to_ship = all(
        row["reserved_quantity"] >= row["remaining_quantity"]
        for row in product_lines
    )
    if order.status == "DRAFT":
        next_action = "CONFIRM"
    elif order.status == "FULFILLED":
        next_action = "COMPLETED"
    elif order.status == "CANCELLED":
        next_action = "CANCELLED"
    elif ready_to_ship:
        next_action = "SHIP"
    elif missing_bom:
        next_action = "CONFIGURE_BOM"
    elif has_shortage:
        next_action = "PURCHASE"
    elif production_required:
        next_action = "PRODUCE"
    else:
        next_action = "CHECK_STOCK"

    return {
        "order_id": order.id,
        "order_no": order.order_no,
        "status": order.status,
        "ready_to_ship": ready_to_ship,
        "next_action": next_action,
        "product_lines": product_lines,
        "material_lines": material_lines,
        "missing_bom": missing_bom,
        "estimated_completion_at": (
            order.estimated_completion_at.isoformat() if order.estimated_completion_at else None
        ),
        "eta_calculated_at": order.eta_calculated_at.isoformat() if order.eta_calculated_at else None,
        "eta_reliable": order.eta_reliable,
        "eta_note": order.eta_note,
    }


def prepare_order_stock(db: Session, order: SalesOrder) -> dict:
    raise HTTPException(410, "订单级备货已停用，请使用待购买、订单排产和生产入库流程")


def release_order_reservations(db: Session, order: SalesOrder) -> None:
    line_ids = [line.id for line in order.items]
    if line_ids:
        reservations = db.scalars(
            select(StockReservation).where(StockReservation.order_item_id.in_(line_ids))
        ).all()
        for reservation in reservations:
            reservation.quantity = 0
            reservation.status = "RELEASED"
    for line in order.items:
        line.reserved_quantity = 0


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
        customer_address="上海市浦东新区", status="CONFIRMED", order_date=date.today(), required_date=date.today(), notes="演示客单"
    )
    order.items = [SalesOrderItem(product_id=products[0].id, quantity=3, reference_price=239, unit_price=239, line_total=717)]
    order.total_amount = 717
    db.add(order)
    db.commit()
