from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from math import floor

from sqlalchemy import and_, delete, func, or_, select
from sqlalchemy.orm import Session, selectinload

from .models import (
    ExternalProcessingBatch,
    InventoryItem,
    ProductionAllocation,
    ProductionCalendarException,
    ProductionMaterialReservation,
    ProductionRun,
    ProductionSetting,
    ProductBomItem,
    PurchaseCommitment,
    SalesOrder,
    SalesOrderItem,
)
from .services import RESERVATION_STATUSES, rebalance_product_reservations, serial


SECONDS_PER_DAY = 86400.0
PARALLEL_IMPROVEMENT_THRESHOLD = 0.05


def is_working_day(db: Session, check_date: date) -> bool:
    """检查给定日期是否为工作日。优先查日历例外，再查默认工作日设置。"""
    exception = db.scalar(
        select(ProductionCalendarException)
        .where(ProductionCalendarException.exception_date == check_date)
    )
    if exception:
        return bool(exception.is_working_day)
    settings = db.get(ProductionSetting, 1)
    weekdays_str = (settings.working_weekdays if settings else "1,2,3,4,5") or "1,2,3,4,5"
    try:
        weekdays = {int(d.strip()) for d in weekdays_str.split(",") if d.strip()}
    except ValueError:
        weekdays = {1, 2, 3, 4, 5}
    return check_date.isoweekday() in weekdays


def next_working_start(db: Session, from_time: datetime) -> datetime:
    """返回 from_time 之后最近的工作日开工时间（当日 08:00 或次日 08:00）。"""
    check_date = from_time.date()
    day_start = datetime.combine(check_date, time(8, 0))
    if is_working_day(db, check_date) and from_time <= day_start:
        return day_start
    for _ in range(30):
        check_date += timedelta(days=1)
        if is_working_day(db, check_date):
            return datetime.combine(check_date, time(8, 0))
    return from_time


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
    material_shortages = []
    if run.status == "PLANNED":
        reservation_map = {
            r.part_id: float(r.quantity)
            for r in (run.material_reservations or [])
            if r.status == "ACTIVE"
        }
        for component in run.product.bom_components:
            required = float(component.quantity) * int(run.planned_quantity)
            reserved = reservation_map.get(component.part_id, 0.0)
            if reserved + 1e-9 < required:
                material_shortages.append({
                    "part_id": component.part_id,
                    "sku": component.part.sku,
                    "name": component.part.name,
                    "unit": component.part.unit,
                    "required_quantity": required,
                    "reserved_quantity": reserved,
                    "shortage_quantity": required - reserved,
                })
    return {
        "id": run.id,
        "run_no": run.run_no,
        "product_id": run.product_id,
        "product_sku": run.product.sku,
        "product_name": run.product.name,
        "unit": run.product.unit,
        "requires_external_processing": bool(run.product.requires_external_processing),
        "external_process_name": run.product.external_process_name or "",
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
        "source_type": run.source_type or "ORDER",
        "notes": run.notes or "",
        "status": run.status,
        "scrap_quantity": int(run.scrap_quantity or 0),
        "termination_reason": run.termination_reason or "",
        "terminated_at": run.terminated_at.isoformat() if run.terminated_at else None,
        "workflow_version": int(run.workflow_version or 1),
        "materials_ready": not material_shortages,
        "material_shortages": material_shortages,
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


def rebuild_material_reservations(db: Session) -> None:
    """按 planned_start_at、run_id 排序，依次从真实零件库存分配物料预留。

    确保多个 PLANNED 批次不会同时看到同一批库存可用；先排产的批次优先占用。
    """
    runs = db.scalars(
        select(ProductionRun)
        .where(ProductionRun.status == "PLANNED")
        .options(
            selectinload(ProductionRun.product)
            .selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part),
        )
        .order_by(ProductionRun.planned_start_at, ProductionRun.id)
    ).all()
    existing = {
        (r.production_run_id, r.part_id): r
        for r in db.scalars(
            select(ProductionMaterialReservation).where(
                ProductionMaterialReservation.status == "ACTIVE"
            )
        ).all()
    }
    part_stock: dict[int, float] = {}
    seen_runs: set[int] = set()
    for run in runs:
        seen_runs.add(run.id)
        for component in run.product.bom_components:
            required = float(component.quantity) * int(run.planned_quantity)
            part = component.part
            stock = part_stock.setdefault(part.id, float(part.stock_qty))
            allocated = min(required, max(stock, 0))
            reservation = existing.get((run.id, part.id))
            if reservation is None:
                reservation = ProductionMaterialReservation(
                    production_run_id=run.id,
                    part_id=part.id,
                    quantity=allocated,
                    status="ACTIVE",
                )
                db.add(reservation)
            else:
                reservation.quantity = allocated
                reservation.status = "ACTIVE"
            part_stock[part.id] = stock - allocated
    stale = db.scalars(
        select(ProductionMaterialReservation).where(
            ProductionMaterialReservation.status == "ACTIVE",
            ProductionMaterialReservation.production_run_id.notin_(seen_runs) if seen_runs else True,
        )
    ).all()
    for reservation in stale:
        reservation.status = "RELEASED"
    db.flush()


def list_production_runs(db: Session, status: str | None = None) -> list[dict]:
    query = select(ProductionRun).options(
        selectinload(ProductionRun.product)
        .selectinload(InventoryItem.bom_components)
        .selectinload(ProductBomItem.part),
        selectinload(ProductionRun.allocations)
        .selectinload(ProductionAllocation.order_item)
        .selectinload(SalesOrderItem.order),
        selectinload(ProductionRun.material_reservations),
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
    product_id: int,
    daily_capacity: int,
    quantity: float,
    now: datetime,
    line_available: dict[int, datetime],
    mold_available: dict[tuple[int, int], datetime],
    mold_count: int,
    line_count: int,
) -> tuple[list[dict], datetime] | None:
    effective_capacity = float(daily_capacity)
    if effective_capacity <= 0:
        return None
    candidates = []
    rate = effective_capacity / SECONDS_PER_DAY
    for line_slot in range(1, max(int(line_count), 1) + 1):
        for mold_slot in range(1, max(int(mold_count), 1) + 1):
            start = max(
                now,
                line_available.get(line_slot, now),
                mold_available.get((product_id, mold_slot), now),
            )
            candidates.append({
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


def _recalculate_plan_impl(
    db: Session,
    now: datetime,
    skip_rebuild_auto: bool = False,
) -> dict:
    """按 FCFS、最早完成资源组合和同产品合批，重算全部未完结客单 ETA。

    skip_rebuild_auto=True 时跳过删除和重建未锁定 ORDER 批次，
    用于自主计划创建后只需重算 ETA 和物料预留的场景。
    """
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
    if not skip_rebuild_auto:
        planned_ids = db.scalars(
            select(ProductionRun.id).where(
                ProductionRun.status == "PLANNED",
                ProductionRun.schedule_locked.is_(False),
                ProductionRun.source_type == "ORDER",
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
            line.pipeline_quantity = 0
            line.production_required_quantity = max(
                int(line.quantity)
                - int(line.shipped_quantity or 0)
                - int(line.reserved_quantity or 0),
                0,
            )
            line.estimated_completion_at = now if line.production_required_quantity <= 1e-9 else None
            line.eta_reliable = line.production_required_quantity <= 1e-9
            line.eta_note = "成品库存已预留" if line.eta_reliable else ""

    # 已完工但仍在厂内半成品区或外协单位的数量也是在途供给，不能重复排产。
    # 按与成品预留相同的交期顺序，把在途供给分配给订单行。
    pipeline_available = {
        product_id: int((db.get(InventoryItem, product_id).semi_finished_qty or 0)
                        + (db.get(InventoryItem, product_id).processing_qty or 0))
        for product_id in product_ids
    }
    for order in active_orders:
        for line in order.items:
            available = max(pipeline_available.get(line.product_id, 0), 0)
            raw_required = int(line.production_required_quantity or 0)
            allocated = min(raw_required, available)
            line.pipeline_quantity = allocated
            line.production_required_quantity = raw_required - allocated
            pipeline_available[line.product_id] = available - allocated
            if allocated and line.production_required_quantity <= 0:
                line.eta_note = "已有半成品或外协在途，待加工回厂"
                line.eta_reliable = False
                line.estimated_completion_at = None

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
    # 自主补库存计划同样是未来供给。新客单在计划创建后进入时，
    # 将尚未分配的计划产量按交期补给订单，避免系统重复生成同产品批次。
    allocated_by_line: dict[int, float] = defaultdict(float)
    for run in fixed_runs:
        for allocation in run.allocations:
            allocated_by_line[allocation.order_item_id] += float(allocation.quantity)
    prioritized_lines = [
        line
        for order in active_orders
        for line in order.items
        if float(line.production_required_quantity or 0) > 1e-9
    ]
    for run in sorted(fixed_runs, key=lambda row: (row.planned_end_at, row.id)):
        if run.source_type != "REPLENISHMENT" or run.status != "PLANNED":
            continue
        remaining_supply = max(
            int(run.planned_quantity)
            - sum(int(allocation.quantity) for allocation in run.allocations),
            0,
        )
        sequence = max(
            (allocation.sequence for allocation in run.allocations),
            default=0,
        ) + 1
        for line in prioritized_lines:
            if line.product_id != run.product_id or remaining_supply <= 0:
                continue
            needed = max(
                int(line.production_required_quantity or 0)
                - int(allocated_by_line.get(line.id, 0)),
                0,
            )
            quantity = min(needed, remaining_supply)
            if quantity <= 0:
                continue
            allocation = ProductionAllocation(
                production_run=run,
                order_item_id=line.id,
                quantity=quantity,
                sequence=sequence,
                estimated_completion_at=run.planned_end_at,
            )
            db.add(allocation)
            allocated_by_line[line.id] += quantity
            remaining_supply -= quantity
            sequence += 1
    db.flush()

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
    material_eta_constraints: list[datetime] = []
    for part_id, required in material_required.items():
        part = db.get(InventoryItem, part_id)
        if not part:
            shortage_products.update(products_with_part[part_id])
            continue
        available = float(part.stock_qty)
        shortfall = required - available
        if shortfall <= 1e-9:
            continue
        commitments = db.scalars(
            select(PurchaseCommitment)
            .where(
                PurchaseCommitment.part_id == part_id,
                PurchaseCommitment.status == "PLANNED",
            )
            .order_by(PurchaseCommitment.expected_arrival_at)
        ).all() if shortfall > 0 else []
        committed_quantity = sum(float(c.quantity) for c in commitments)
        if committed_quantity + available + 1e-9 >= required:
            for c in commitments:
                material_eta_constraints.append(c.expected_arrival_at)
        else:
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
        product = demands[0]["line"].product
        choice = _choose_resources(
            product_id,
            int(product.daily_capacity or 0),
            total_quantity,
            now,
            line_available,
            mold_available,
            max(int(product.mold_count or 1), 1),
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
                workflow_version=2,
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
        elif material_eta_constraints:
            latest_material = max(material_eta_constraints)
            note = f"原材料在途，预计 {latest_material:%m-%d} 到货后可排产"
            for demand in demands:
                if demand["line"].estimated_completion_at and demand["line"].estimated_completion_at < latest_material:
                    demand["line"].estimated_completion_at = latest_material
        else:
            note = ""
        if product.requires_external_processing:
            ext_batches = db.scalars(
                select(ExternalProcessingBatch)
                .where(
                    ExternalProcessingBatch.product_id == product_id,
                    ExternalProcessingBatch.expected_return_at.is_not(None),
                    ExternalProcessingBatch.returned_quantity < ExternalProcessingBatch.quantity,
                )
                .order_by(ExternalProcessingBatch.expected_return_at.desc())
            ).all()
            if ext_batches:
                latest_ext_return = ext_batches[0].expected_return_at
                for demand in demands:
                    if demand["line"].estimated_completion_at and demand["line"].estimated_completion_at < latest_ext_return:
                        demand["line"].estimated_completion_at = latest_ext_return
                if not note:
                    note = f"外协在途，预计 {latest_ext_return:%m-%d} 回厂"
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
    rebuild_material_reservations(db)
    return {
        "calculated_at": now.isoformat(),
        "active_order_count": len(active_orders),
        "product_demand_count": len(demands_by_product),
        "created_run_count": len(created_runs),
        "unavailable_product_ids": unavailable_products,
        "material_shortage_product_ids": sorted(shortage_products),
        "missing_bom_product_ids": sorted(missing_bom_products),
    }


def recalculate_production_plan(db: Session, now: datetime | None = None) -> dict:
    """全量重算生产计划的统一入口。"""
    return _recalculate_plan_impl(db, now or datetime.now())


def production_demand_summary(db: Session) -> list[dict]:
    """从订单剩余缺口和有效批次分配推导生产总量、已排产与待排产。"""
    rows = db.execute(
        select(
            SalesOrderItem.product_id,
            InventoryItem.sku,
            InventoryItem.name,
            InventoryItem.unit,
            func.coalesce(func.sum(SalesOrderItem.production_required_quantity), 0),
        )
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .join(InventoryItem, InventoryItem.id == SalesOrderItem.product_id)
        .where(SalesOrder.status.in_(RESERVATION_STATUSES))
        .group_by(
            SalesOrderItem.product_id,
            InventoryItem.sku,
            InventoryItem.name,
            InventoryItem.unit,
        )
        .order_by(InventoryItem.sku)
    ).all()
    scheduled = dict(db.execute(
        select(
            ProductionRun.product_id,
            func.coalesce(func.sum(ProductionAllocation.quantity), 0),
        )
        .join(
            ProductionAllocation,
            ProductionAllocation.production_run_id == ProductionRun.id,
        )
        .where(ProductionRun.status.in_(("PLANNED", "RUNNING")))
        .group_by(ProductionRun.product_id)
    ).all())
    return [
        {
            "product_id": product_id,
            "sku": sku,
            "name": name,
            "unit": unit,
            "total_production_required": int(total or 0),
            "scheduled_quantity": min(int(scheduled.get(product_id, 0)), int(total or 0)),
            "unscheduled_quantity": max(int(total or 0) - int(scheduled.get(product_id, 0)), 0),
        }
        for product_id, sku, name, unit, total in rows
        if int(total or 0) > 0
    ]


def purchase_requirement_summary(
    db: Session,
    shortages_only: bool = True,
) -> list[dict]:
    """将全部未完成生产需求按 BOM 展开并全局汇总，同一库存只扣一次。"""
    demands = production_demand_summary(db)
    required: dict[int, dict] = {}
    for demand in demands:
        components = db.scalars(
            select(ProductBomItem)
            .where(ProductBomItem.product_id == demand["product_id"])
            .options(selectinload(ProductBomItem.part))
        ).all()
        for component in components:
            row = required.setdefault(component.part_id, {
                "part_id": component.part_id,
                "sku": component.part.sku,
                "name": component.part.name,
                "unit": component.part.unit,
                "supply_mode": component.part.supply_mode or "STOCK",
                "current_stock": float(component.part.stock_qty),
                "total_required": 0.0,
                "products": [],
            })
            row["total_required"] += (
                float(component.quantity) * demand["total_production_required"]
            )
            if demand["name"] not in row["products"]:
                row["products"].append(demand["name"])
    result = []
    for row in required.values():
        row["total_required"] = round(row["total_required"], 6)
        row["shortage_quantity"] = round(
            max(row["total_required"] - row["current_stock"], 0), 6
        )
        row["involved_products"] = "、".join(row.pop("products")[:5])
        if not shortages_only or row["shortage_quantity"] > 0:
            result.append(row)
    return sorted(result, key=lambda row: (-row["shortage_quantity"], row["sku"]))
