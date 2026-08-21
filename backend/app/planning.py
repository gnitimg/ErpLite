from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from math import floor

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    InventoryItem,
    ProductionAllocation,
    ProductionCapability,
    ProductionRun,
    ProductionSetting,
    ProductBomItem,
    SalesOrder,
    SalesOrderItem,
)
from .services import RESERVATION_STATUSES, rebalance_product_reservations, serial


SECONDS_PER_DAY = 86400.0
PARALLEL_IMPROVEMENT_THRESHOLD = 0.05


def _integer_shares(total: int, weights: list[float]) -> list[int]:
    """按最大余数法分配整数件，确保各份之和严格等于总数。"""
    if total <= 0 or not weights:
        return [0 for _ in weights]
    weight_sum = sum(weights)
    raw = [total * weight / weight_sum for weight in weights]
    shares = [int(value) for value in raw]
    remainder = total - sum(shares)
    order = sorted(range(len(raw)), key=lambda index: raw[index] - shares[index], reverse=True)
    for index in order[:remainder]:
        shares[index] += 1
    return shares


def _run_dict(run: ProductionRun) -> dict:
    return {
        "id": run.id,
        "run_no": run.run_no,
        "product_id": run.product_id,
        "product_sku": run.product.sku,
        "product_name": run.product.name,
        "unit": run.product.unit,
        "line_slot": run.line_slot,
        "mold_slot": run.mold_slot,
        "mold_count": max(int(run.product.mold_count or 1), 1),
        "planned_quantity": run.planned_quantity,
        "produced_quantity": run.produced_quantity,
        "planned_start_at": run.planned_start_at.isoformat(),
        "planned_end_at": run.planned_end_at.isoformat(),
        "actual_start_at": run.actual_start_at.isoformat() if run.actual_start_at else None,
        "actual_end_at": run.actual_end_at.isoformat() if run.actual_end_at else None,
        "effective_daily_capacity": run.effective_daily_capacity,
        "schedule_locked": run.schedule_locked,
        "status": run.status,
        "allocations": [
            {
                "id": allocation.id,
                "order_item_id": allocation.order_item_id,
                "order_id": allocation.order_item.order_id,
                "order_no": allocation.order_item.order.order_no,
                "customer_name": allocation.order_item.order.customer_name,
                "quantity": allocation.quantity,
                "sequence": allocation.sequence,
                "estimated_completion_at": (
                    allocation.estimated_completion_at.isoformat()
                    if allocation.estimated_completion_at else None
                ),
            }
            for allocation in sorted(run.allocations, key=lambda row: row.sequence)
        ],
    }


def list_production_runs(db: Session, status: str | None = None) -> list[dict]:
    query = select(ProductionRun).options(
        selectinload(ProductionRun.product),
        selectinload(ProductionRun.allocations)
        .selectinload(ProductionAllocation.order_item)
        .selectinload(SalesOrderItem.order),
    )
    if status:
        query = query.where(ProductionRun.status == status.upper())
    rows = db.scalars(
        query.order_by(ProductionRun.planned_start_at, ProductionRun.id)
    ).all()
    return [_run_dict(row) for row in rows]


def _finish_for_resources(resources: list[dict], quantity: float) -> datetime:
    earliest = min(resource["start"] for resource in resources)
    slowest_rate = min(resource["rate"] for resource in resources)
    low = earliest
    high = earliest + timedelta(seconds=max(quantity / slowest_rate, 1))
    for _ in range(60):
        midpoint = low + (high - low) / 2
        produced = sum(
            resource["rate"] * max((midpoint - resource["start"]).total_seconds(), 0)
            for resource in resources
        )
        if produced >= quantity:
            high = midpoint
        else:
            low = midpoint
    return high


def _choose_resources(
    capabilities: list[ProductionCapability],
    quantity: float,
    now: datetime,
    line_available: dict[int, datetime],
    mold_available: dict[tuple[int, int], datetime],
    mold_count: int,
    line_count: int,
) -> tuple[list[dict], datetime] | None:
    candidates = []
    for capability in capabilities:
        effective_capacity = (
            float(capability.nominal_daily_capacity) * float(capability.safety_factor)
        )
        if effective_capacity <= 0:
            continue
        rate = effective_capacity / SECONDS_PER_DAY
        for line_slot in range(1, max(int(line_count), 1) + 1):
            for mold_slot in range(1, max(int(mold_count), 1) + 1):
                start = max(
                    now,
                    line_available.get(line_slot, now),
                    mold_available.get((capability.product_id, mold_slot), now),
                )
                candidates.append({
                    "capability": capability,
                    "line_slot": line_slot,
                    "mold_slot": mold_slot,
                    "start": start,
                    "rate": rate,
                    "effective_capacity": effective_capacity,
                })
    if not candidates:
        return None

    candidates.sort(key=lambda row: row["start"] + timedelta(seconds=quantity / row["rate"]))
    selected = [candidates[0]]
    current_finish = _finish_for_resources(selected, quantity)
    used_lines = {candidates[0]["line_slot"]}
    used_mold_slots = {candidates[0]["mold_slot"]}
    while True:
        best_candidate = None
        best_finish = current_finish
        for candidate in candidates[1:]:
            if candidate["line_slot"] in used_lines or candidate["mold_slot"] in used_mold_slots:
                continue
            trial_finish = _finish_for_resources(selected + [candidate], quantity)
            if trial_finish < best_finish:
                best_candidate = candidate
                best_finish = trial_finish
        if best_candidate is None:
            break
        current_seconds = max((current_finish - now).total_seconds(), 1)
        improvement = (current_finish - best_finish).total_seconds() / current_seconds
        if improvement < PARALLEL_IMPROVEMENT_THRESHOLD:
            break
        selected.append(best_candidate)
        used_lines.add(best_candidate["line_slot"])
        used_mold_slots.add(best_candidate["mold_slot"])
        current_finish = best_finish
    return selected, current_finish


def _allocate_supply(
    db: Session,
    runs: list[ProductionRun],
    demands: list[dict],
) -> None:
    if not runs or not demands:
        return
    events = sorted({run.planned_start_at for run in runs} | {run.planned_end_at for run in runs})
    remaining = {demand["line"].id: int(demand["quantity"]) for demand in demands}
    demand_index = 0
    allocation_quantities: dict[tuple[int, int], float] = defaultdict(float)
    allocation_eta: dict[tuple[int, int], datetime] = {}

    for interval_start, interval_end in zip(events, events[1:]):
        active = [
            run for run in runs
            if run.planned_start_at <= interval_start and run.planned_end_at >= interval_end
        ]
        if not active:
            continue
        rates = {
            run.id: float(run.effective_daily_capacity) / SECONDS_PER_DAY
            for run in active
        }
        total_rate = sum(rates.values())
        cursor = interval_start
        while demand_index < len(demands) and cursor < interval_end:
            demand = demands[demand_index]
            line = demand["line"]
            needed = remaining[line.id]
            interval_capacity = total_rate * (interval_end - cursor).total_seconds()
            produced = needed if needed <= interval_capacity + 1e-6 else floor(interval_capacity)
            if produced <= 0:
                break
            duration_seconds = produced / total_rate
            completion = cursor + timedelta(seconds=duration_seconds)
            shares = _integer_shares(produced, [rates[run.id] for run in active])
            for run, share in zip(active, shares):
                key = (run.id, line.id)
                allocation_quantities[key] += share
                allocation_eta[key] = completion
            remaining[line.id] = needed - produced
            cursor = completion
            if remaining[line.id] <= 1e-6:
                line.estimated_completion_at = completion
                demand_index += 1

    run_by_id = {run.id: run for run in runs}
    sequence_by_item = {demand["line"].id: index + 1 for index, demand in enumerate(demands)}
    for (run_id, order_item_id), quantity in allocation_quantities.items():
        db.add(ProductionAllocation(
            production_run=run_by_id[run_id],
            order_item_id=order_item_id,
            quantity=int(quantity),
            sequence=sequence_by_item[order_item_id],
            estimated_completion_at=allocation_eta[(run_id, order_item_id)],
        ))


def recalculate_production_plan(db: Session, now: datetime | None = None) -> dict:
    """按 FCFS、最早完成资源组合和同产品合批，重算全部未完结客单 ETA。"""
    now = now or datetime.now()
    db.flush()
    settings_query = select(ProductionSetting).where(ProductionSetting.id == 1)
    if db.bind and db.bind.dialect.name != "sqlite":
        settings_query = settings_query.with_for_update()
    settings = db.scalar(settings_query)
    if settings is None:
        settings = ProductionSetting(id=1, line_count=1)
        db.add(settings)
        db.flush()
    line_count = max(int(settings.line_count or 1), 1)
    active_orders = db.scalars(
        select(SalesOrder)
        .where(SalesOrder.status.in_(RESERVATION_STATUSES))
        .options(
            selectinload(SalesOrder.items)
            .selectinload(SalesOrderItem.product)
            .selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part)
        )
        .order_by(SalesOrder.required_date, SalesOrder.order_date, SalesOrder.id)
    ).all()
    product_ids = {line.product_id for order in active_orders for line in order.items}
    if product_ids:
        rebalance_product_reservations(db, product_ids)

    # 仅重建未被人工确认的模拟计划；人工排期和生产中批次作为固定时间轴保留。
    planned_ids = db.scalars(
        select(ProductionRun.id).where(
            ProductionRun.status == "PLANNED",
            ProductionRun.schedule_locked.is_(False),
        )
    ).all()
    if planned_ids:
        db.execute(delete(ProductionAllocation).where(
            ProductionAllocation.production_run_id.in_(planned_ids)
        ))
        db.execute(delete(ProductionRun).where(ProductionRun.id.in_(planned_ids)))
    db.flush()

    for order in active_orders:
        order.estimated_completion_at = None
        order.eta_calculated_at = now
        order.eta_reliable = False
        order.eta_note = ""
        for line in order.items:
            line.production_required_quantity = max(
                float(line.quantity) - float(line.reserved_quantity or 0), 0
            )
            line.estimated_completion_at = now if line.production_required_quantity <= 1e-9 else None
            line.eta_reliable = line.production_required_quantity <= 1e-9
            line.eta_note = "成品库存已预留" if line.eta_reliable else ""

    fixed_runs = db.scalars(
        select(ProductionRun)
        .where(
            or_(
                ProductionRun.status == "RUNNING",
                and_(
                    ProductionRun.status == "PLANNED",
                    ProductionRun.schedule_locked.is_(True),
                ),
            ),
        )
        .options(selectinload(ProductionRun.allocations))
    ).all()
    running_allocated: dict[int, float] = defaultdict(float)
    running_eta: dict[int, datetime] = {}
    for run in fixed_runs:
        for allocation in run.allocations:
            running_allocated[allocation.order_item_id] += float(allocation.quantity)
            if allocation.estimated_completion_at:
                running_eta[allocation.order_item_id] = max(
                    running_eta.get(allocation.order_item_id, allocation.estimated_completion_at),
                    allocation.estimated_completion_at,
                )

    demands_by_product: dict[int, list[dict]] = defaultdict(list)
    for order in active_orders:
        for line in order.items:
            remaining = max(
                float(line.production_required_quantity)
                - running_allocated.get(line.id, 0),
                0,
            )
            if remaining <= 1e-9:
                if line.production_required_quantity > 1e-9:
                    line.estimated_completion_at = running_eta.get(line.id)
                    line.eta_reliable = bool(line.estimated_completion_at)
                    line.eta_note = "已由人工排期或生产中批次覆盖"
                continue
            demands_by_product[line.product_id].append({
                "line": line,
                "order": order,
                "quantity": remaining,
            })

    line_available: dict[int, datetime] = defaultdict(lambda: now)
    mold_available: dict[tuple[int, int], datetime] = defaultdict(lambda: now)
    for run in fixed_runs:
        line_slot = max(int(run.line_slot or 1), 1)
        line_available[line_slot] = max(line_available[line_slot], run.planned_end_at)
        mold_key = (run.product_id, max(int(run.mold_slot or 1), 1))
        mold_available[mold_key] = max(mold_available[mold_key], run.planned_end_at)

    capabilities = db.scalars(
        select(ProductionCapability)
        .where(ProductionCapability.active.is_(True))
    ).all()
    capabilities_by_product: dict[int, list[ProductionCapability]] = defaultdict(list)
    for capability in capabilities:
        capabilities_by_product[capability.product_id].append(capability)

    material_required: dict[int, float] = defaultdict(float)
    products_with_part: dict[int, set[int]] = defaultdict(set)
    missing_bom_products: set[int] = set()
    for product_id, demands in demands_by_product.items():
        total = sum(row["quantity"] for row in demands)
        product = demands[0]["line"].product
        if not product.bom_components:
            missing_bom_products.add(product_id)
        for component in product.bom_components:
            material_required[component.part_id] += float(component.quantity) * total
            products_with_part[component.part_id].add(product_id)
    shortage_products: set[int] = set()
    for part_id, required in material_required.items():
        part = db.get(InventoryItem, part_id)
        if not part or float(part.stock_qty) + 1e-9 < required:
            shortage_products.update(products_with_part[part_id])

    product_order = sorted(
        demands_by_product,
        key=lambda product_id: (
            demands_by_product[product_id][0]["order"].required_date,
            demands_by_product[product_id][0]["order"].order_date,
            demands_by_product[product_id][0]["order"].id,
            product_id,
        ),
    )
    created_runs: list[ProductionRun] = []
    unavailable_products: list[int] = []
    for product_id in product_order:
        demands = demands_by_product[product_id]
        total_quantity = int(sum(row["quantity"] for row in demands))
        choice = _choose_resources(
            capabilities_by_product.get(product_id, []),
            total_quantity,
            now,
            line_available,
            mold_available,
            max(int(demands[0]["line"].product.mold_count or 1), 1),
            line_count,
        )
        if choice is None:
            unavailable_products.append(product_id)
            for demand in demands:
                demand["line"].eta_note = "未配置可用的产品日产能力"
            continue
        resources, common_finish = choice
        runs: list[ProductionRun] = []
        planned_shares = _integer_shares(
            total_quantity,
            [
                resource["rate"] * max(
                    (common_finish - resource["start"]).total_seconds(), 0
                )
                for resource in resources
            ],
        )
        for resource, planned_quantity in zip(resources, planned_shares):
            if planned_quantity <= 0:
                continue
            capability = resource["capability"]
            run = ProductionRun(
                run_no=serial("PR"),
                product_id=product_id,
                line_id=None,
                line_slot=resource["line_slot"],
                mold_id=None,
                mold_slot=resource["mold_slot"],
                planned_quantity=planned_quantity,
                produced_quantity=0,
                planned_start_at=resource["start"],
                planned_end_at=common_finish,
                effective_daily_capacity=resource["effective_capacity"],
                status="PLANNED",
            )
            db.add(run)
            runs.append(run)
            created_runs.append(run)
            line_available[resource["line_slot"]] = common_finish
            mold_available[(product_id, resource["mold_slot"])] = common_finish
        db.flush()
        _allocate_supply(db, runs, demands)
        reliable = (
            product_id not in shortage_products
            and product_id not in missing_bom_products
        )
        if product_id in missing_bom_products:
            note = "产品未配置 BOM；机器排程 ETA 仅供参考，暂不可承诺"
        elif product_id in shortage_products:
            note = "BOM 原材料不足；机器排程 ETA 仅供参考，暂不可承诺"
        else:
            note = ""
        for demand in demands:
            demand["line"].eta_reliable = reliable and bool(
                demand["line"].estimated_completion_at
            )
            demand["line"].eta_note = note or "按当前产能与资源占用模拟"

    for order in active_orders:
        item_etas = [line.estimated_completion_at for line in order.items]
        if item_etas and all(item_etas):
            order.estimated_completion_at = max(item_etas)
        order.eta_reliable = bool(order.items) and all(
            line.eta_reliable for line in order.items
        )
        notes = list(dict.fromkeys(line.eta_note for line in order.items if line.eta_note))
        order.eta_note = "；".join(notes)[:500]

    db.flush()
    return {
        "calculated_at": now.isoformat(),
        "active_order_count": len(active_orders),
        "product_demand_count": len(demands_by_product),
        "created_run_count": len(created_runs),
        "unavailable_product_ids": unavailable_products,
        "material_shortage_product_ids": sorted(shortage_products),
        "missing_bom_product_ids": sorted(missing_bom_products),
    }
