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
DEFAULT_WORKING_WEEKDAYS = "1,2,3,4,5"
MAX_CALENDAR_LOOKAHEAD_DAYS = 400


class WorkingCalendar:
    """进程内生产日历：预载 working_weekdays 与例外，供排产热循环零查询判定。

    时间抽象：一个工作日 = 一个完整生产日（贡献 daily_capacity 全部产能），
    休息日产能为零；起止时刻的时分秒保留为展示语义，不影响产能计算。
    """

    def __init__(self, db: Session):
        settings = db.get(ProductionSetting, 1)
        weekdays_str = (settings.working_weekdays if settings else None) or DEFAULT_WORKING_WEEKDAYS
        try:
            self._weekdays = {int(d.strip()) for d in weekdays_str.split(",") if d.strip()}
        except ValueError:
            self._weekdays = {1, 2, 3, 4, 5}
        self._exceptions = {
            row.exception_date: bool(row.is_working_day)
            for row in db.scalars(select(ProductionCalendarException)).all()
        }

    def is_working_day(self, day: date) -> bool:
        if day in self._exceptions:
            return self._exceptions[day]
        return day.isoweekday() in self._weekdays

    def next_working_day(self, day: date) -> date:
        for _ in range(MAX_CALENDAR_LOOKAHEAD_DAYS):
            day = day + timedelta(days=1)
            if self.is_working_day(day):
                return day
        return day

    def add_duration(self, start_at: datetime, production_days: float) -> datetime:
        """按生产日历推进 production_days 个生产日，返回结束时刻。

        不足一天的份额落在某个工作日内（时钟按比例推进，可跨午夜）；
        整日消耗后结束时刻落在下一个工作日的同一时分秒。
        连续工作日下与旧的“连续秒”算法结果一致。
        """
        remaining = float(production_days)
        current = start_at
        for _ in range(MAX_CALENDAR_LOOKAHEAD_DAYS):
            if remaining <= 1e-9:
                return current
            if self.is_working_day(current.date()):
                if abs(remaining - 1.0) <= 1e-9:
                    return datetime.combine(self.next_working_day(current.date()), current.time())
                if remaining < 1.0:
                    return current + timedelta(days=remaining)
                remaining -= 1.0
            current = datetime.combine(current.date() + timedelta(days=1), start_at.time())
        return current

    def snap_to_working(self, start: datetime) -> datetime:
        """把起点吸附到最近的工作日同一时刻：批次不得显示休息日开工。"""
        for _ in range(MAX_CALENDAR_LOOKAHEAD_DAYS):
            if self.is_working_day(start.date()):
                return start
            start = datetime.combine(start.date() + timedelta(days=1), start.time())
        return start

    def working_span(self, start: datetime, end: datetime) -> float:
        """[start, end] 之间的生产日数（份额权重用，天粒度近似）。"""
        if end <= start:
            return 0.0
        total = 0.0
        day = start.date()
        while day <= end.date():
            if self.is_working_day(day):
                if day == start.date() and day == end.date():
                    total += max((end - start).total_seconds() / 86400.0, 0.0)
                else:
                    total += 1.0
            day += timedelta(days=1)
        return total


class MaterialTimeline:
    """零件供给时间轴（计划预测用）：可用库存 + PLANNED 采购承诺按到货顺序被依次消耗。

    planner 按生产优先顺序对每个待排产品消耗 BOM 需求，得到该批生产
    "全部材料可满足"的最早时间——run 级结果，而不是一个零件一个全局日期。
    与 ProductionMaterialReservation（当前实际库存的开工占用）是两个并存的
    概念：这里是预测，那里是占用。
    """

    def __init__(self, db: Session, now: datetime):
        self._now = now
        self._shortage: dict[int, float] = defaultdict(float)
        reserved_by_part: dict[int, float] = defaultdict(float)
        for part_id, quantity in db.execute(
            select(
                ProductionMaterialReservation.part_id,
                func.coalesce(func.sum(ProductionMaterialReservation.quantity), 0),
            )
            .where(ProductionMaterialReservation.status == "ACTIVE")
            .group_by(ProductionMaterialReservation.part_id)
        ).all():
            reserved_by_part[part_id] = float(quantity)
        # 固定批次的材料已从现有库存预留，不能重复许诺给新计划。
        self._stock: dict[int, float] = {}
        for part_id, stock_qty in db.execute(
            select(InventoryItem.id, InventoryItem.stock_qty)
            .where(InventoryItem.kind == "PART")
        ).all():
            self._stock[part_id] = max(
                float(stock_qty or 0) - reserved_by_part.get(part_id, 0.0), 0.0
            )
        self._commitments: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
        for commitment in db.scalars(
            select(PurchaseCommitment).where(PurchaseCommitment.status == "PLANNED")
        ).all():
            arrival = commitment.expected_arrival_at or now
            self._commitments[commitment.part_id].append(
                (max(arrival, now), float(commitment.quantity))
            )
        for lots in self._commitments.values():
            lots.sort()

    def consume(self, part_id: int, quantity: float) -> datetime | None:
        """按时间轴消耗 quantity 件；返回满足时刻，供给不足时返回 None。"""
        remaining = float(quantity)
        if remaining <= 1e-9:
            return self._now
        available_at = self._now
        stock = self._stock.get(part_id, 0.0)
        if stock > 1e-9:
            taken = min(stock, remaining)
            self._stock[part_id] = stock - taken
            remaining -= taken
        lots = self._commitments.get(part_id)
        while remaining > 1e-9 and lots:
            arrival, lot_quantity = lots[0]
            taken = min(lot_quantity, remaining)
            lots[0] = (arrival, lot_quantity - taken)
            remaining -= taken
            available_at = max(available_at, arrival)
            if lot_quantity - taken <= 1e-9:
                lots.pop(0)
        if remaining > 1e-9:
            self._shortage[part_id] += remaining
            return None
        return available_at

    def shortage_parts(self) -> dict[int, float]:
        return dict(self._shortage)


def is_working_day(db: Session, check_date: date) -> bool:
    """检查给定日期是否为工作日。优先查日历例外，再查默认工作日设置。"""
    return WorkingCalendar(db).is_working_day(check_date)


def calculate_production_end(
    db: Session,
    start_at: datetime,
    quantity: float,
    daily_capacity: float,
    calendar: WorkingCalendar | None = None,
) -> datetime:
    """统一的生批结束时间计算：数量 / 日产能 = 生产日数，按生产日历推进。

    自动排产、自主补库存、人工拖动改期、取消缩量全部必须走这一个函数，
    禁止再出现 planned_start + 连续秒 的旁路算法。
    """
    capacity = max(float(daily_capacity or 0), 1e-9)
    cal = calendar or WorkingCalendar(db)
    return cal.add_duration(start_at, float(quantity) / capacity)


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


def _finish_for_resources(calendar: WorkingCalendar, resources: list[dict], quantity: float) -> datetime:
    """按生产日历计算完成时间：逐个工作日累加产能，休息日产能为零。"""
    if not resources:
        raise ValueError("至少需要一个生产资源")
    earliest = min(resource["start"] for resource in resources)
    anchor_time = earliest.time()
    day = earliest.date()
    remaining = float(quantity)
    for _ in range(MAX_CALENDAR_LOOKAHEAD_DAYS):
        capacity_today = sum(
            resource["rate"] for resource in resources if resource["start"].date() <= day
        )
        if capacity_today > 1e-9 and calendar.is_working_day(day):
            if remaining <= capacity_today + 1e-9:
                fraction = remaining / capacity_today
                if fraction >= 1.0 - 1e-9:
                    return datetime.combine(calendar.next_working_day(day), anchor_time)
                return datetime.combine(day, anchor_time) + timedelta(days=fraction)
            remaining -= capacity_today
        day += timedelta(days=1)
    return datetime.combine(day, anchor_time)


def _choose_resources(
    calendar: WorkingCalendar,
    product_id: int,
    daily_capacity: int,
    quantity: float,
    now: datetime,
    line_available: dict[int, datetime],
    mold_available: dict[tuple[int, int], datetime],
    mold_count: int,
    line_count: int,
    earliest_start: datetime | None = None,
) -> tuple[list[dict], datetime] | None:
    effective_capacity = float(daily_capacity)
    if effective_capacity <= 0:
        return None
    candidates = []
    rate = effective_capacity  # 以“件/生产日”为速率单位
    for line_slot in range(1, max(int(line_count), 1) + 1):
        for mold_slot in range(1, max(int(mold_count), 1) + 1):
            start = calendar.snap_to_working(max(
                now,
                earliest_start or now,
                line_available.get(line_slot, now),
                mold_available.get((product_id, mold_slot), now),
            ))
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
    current_finish = _finish_for_resources(calendar, selected, quantity)
    used_lines = {candidates[0]["line_slot"]}
    used_mold_slots = {candidates[0]["mold_slot"]}
    while True:
        best_candidate = None
        best_finish = current_finish
        for candidate in candidates[1:]:
            if candidate["line_slot"] in used_lines or candidate["mold_slot"] in used_mold_slots:
                continue
            trial_finish = _finish_for_resources(calendar, selected + [candidate], quantity)
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
    calendar: WorkingCalendar,
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
            run.id: float(run.effective_daily_capacity)
            for run in active
        }
        total_rate = sum(rates.values())
        cursor = interval_start
        while demand_index < len(demands) and cursor < interval_end:
            demand = demands[demand_index]
            line = demand["line"]
            needed = remaining[line.id]
            interval_capacity = total_rate * calendar.working_span(cursor, interval_end)
            produced = needed if needed <= interval_capacity + 1e-6 else floor(interval_capacity)
            if produced <= 0:
                break
            # 完成时刻按生产日历推进（休息日不产出），并夹在区间内。
            completion = min(
                calendar.add_duration(cursor, produced / total_rate),
                interval_end,
            )
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


def acquire_planner_lock(db: Session) -> ProductionSetting:
    """Acquire the planner/rebalance mutex before domain-specific row locks."""
    settings_query = select(ProductionSetting).where(ProductionSetting.id == 1)
    if db.bind and db.bind.dialect.name != "sqlite":
        settings_query = settings_query.with_for_update()
    settings = db.scalar(settings_query)
    if settings is None:
        settings = ProductionSetting(id=1, line_count=1)
        db.add(settings)
        db.flush()
    return settings


def _recalculate_plan_impl(
    db: Session,
    now: datetime,
    skip_rebuild_auto: bool = False,
) -> dict:
    """按 FCFS、最早完成资源组合和同产品合批，重算全部未完结客单 ETA。

    skip_rebuild_auto=True 时跳过删除和重建未锁定 ORDER 批次，
    用于自主计划创建后只需重算 ETA 和物料预留的场景。
    """
    settings = acquire_planner_lock(db)
    db.flush()
    line_count = max(int(settings.line_count or 1), 1)
    calendar = WorkingCalendar(db)
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
            # 生产需求 = 原单剩余 + 待补换货 - 已预留；换货与原单同样消耗库存与产能。
            line.production_required_quantity = max(
                int(line.quantity)
                - int(line.shipped_quantity or 0)
                - int(line.reserved_quantity or 0)
                + int(line.replacement_pending_quantity or 0),
                0,
            )
            line.estimated_completion_at = now if line.production_required_quantity <= 1e-9 else None
            line.eta_reliable = line.production_required_quantity <= 1e-9
            line.eta_note = "成品库存已预留" if line.eta_reliable else ""

    # 半成品（在厂待外协）与外协在途是两类不同的未来供给，必须区分并按
    # 数量+时间分配：在途批次按 (expected_return_at, 剩余量) 逐单分配，
    # 让不同订单拿到各自批次的回厂时间；无预计回厂时间的批次和未送出的
    # 半成品只能覆盖数量、给不出时间 → 相关 ETA 不可靠。
    dated_lots: dict[int, list[tuple[datetime, float]]] = defaultdict(list)
    undated_batches: dict[int, float] = defaultdict(float)
    for batch in db.scalars(
        select(ExternalProcessingBatch).where(
            ExternalProcessingBatch.quantity > ExternalProcessingBatch.returned_quantity
        )
    ).all():
        remaining_qty = float(batch.quantity) - float(batch.returned_quantity or 0)
        if remaining_qty <= 0:
            continue
        if batch.expected_return_at is not None:
            dated_lots[batch.product_id].append((max(batch.expected_return_at, now), remaining_qty))
        else:
            undated_batches[batch.product_id] += remaining_qty
    for lots in dated_lots.values():
        lots.sort()
    semi_pool = {
        product_id: float(db.get(InventoryItem, product_id).semi_finished_qty or 0)
        for product_id in product_ids
    }
    # pipeline_info[line.id] = {"dated"/"undated"/"semi"/"production"/"eta"}
    pipeline_info: dict[int, dict] = {}
    for order in active_orders:
        for line in order.items:
            required = int(line.production_required_quantity or 0)
            if required <= 0:
                continue
            info: dict = {"dated": 0.0, "undated": 0.0, "semi": 0.0, "production": 0.0, "eta": None}
            covered = 0.0
            lots = dated_lots.get(line.product_id)
            while lots and covered < required:
                arrival, lot_quantity = lots[0]
                take = min(lot_quantity, required - covered)
                lots[0] = (arrival, lot_quantity - take)
                covered += take
                info["dated"] += take
                info["eta"] = arrival if info["eta"] is None else max(info["eta"], arrival)
                if lots[0][1] <= 1e-9:
                    lots.pop(0)
            if covered < required and undated_batches.get(line.product_id, 0) > 0:
                take = min(undated_batches[line.product_id], required - covered)
                undated_batches[line.product_id] -= take
                info["undated"] += take
                covered += take
            if covered < required and semi_pool.get(line.product_id, 0) > 0:
                take = min(semi_pool[line.product_id], required - covered)
                semi_pool[line.product_id] -= take
                info["semi"] += take
                covered += take
            line.pipeline_quantity = int(covered)
            info["production"] = max(required - covered, 0)
            line.production_required_quantity = int(info["production"])
            pipeline_info[line.id] = info

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
    # 所有仍会产出的固定批次都是未来供给：RUNNING、人工锁定 PLANNED、自主补库存。
    # 取消订单后留下的空余产量（planned - active allocations）按完成时间依次补给
    # 新需求，绝不重复创建同产品新批次。已 COMPLETED/CANCELLED/TERMINATED 的
    # 批次不会进入 fixed_runs，天然不算供给。RUNNING 厚版暂无实时进度，按
    # planned_quantity 计。
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
        remaining_supply = max(
            int(run.planned_quantity)
            - sum(int(allocation.quantity) for allocation in run.allocations),
            0,
        )
        if remaining_supply <= 0:
            continue
        sequence = max(
            (allocation.sequence for allocation in run.allocations),
            default=0,
        ) + 1
        allocations_by_item = {
            allocation.order_item_id: allocation for allocation in run.allocations
        }
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
            allocation = allocations_by_item.get(line.id)
            if allocation is None:
                allocation = ProductionAllocation(
                    production_run=run,
                    order_item_id=line.id,
                    quantity=quantity,
                    sequence=sequence,
                    estimated_completion_at=run.planned_end_at,
                )
                db.add(allocation)
                allocations_by_item[line.id] = allocation
                sequence += 1
            else:
                allocation.quantity = int(allocation.quantity) + quantity
                allocation.estimated_completion_at = run.planned_end_at
            allocated_by_line[line.id] += quantity
            remaining_supply -= quantity
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

    # 物料时间轴：run 级预测。现有库存先被最靠前的需求用掉，
    # 后续需求只能等更晚的到货——不再是"一个零件一个全局 ETA"。
    timeline = MaterialTimeline(db, now)
    shortage_products: set[int] = set()
    missing_bom_products: set[int] = set()
    for product_id, demands in demands_by_product.items():
        product = demands[0]["line"].product
        if not product.bom_components:
            missing_bom_products.add(product_id)

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
        # 按生产优先顺序消耗物料时间轴，得到本批生产全部材料可满足的最早时间。
        material_available: datetime | None = now
        if product_id not in missing_bom_products:
            for component in product.bom_components:
                got = timeline.consume(
                    component.part_id, float(component.quantity) * total_quantity
                )
                if got is None:
                    material_available = None
                    shortage_products.add(product_id)
                elif material_available is not None and got > material_available:
                    material_available = got
        choice = _choose_resources(
            calendar,
            product_id,
            int(product.daily_capacity or 0),
            total_quantity,
            now,
            line_available,
            mold_available,
            max(int(product.mold_count or 1), 1),
            line_count,
            # 材料可满足时间真正进入资源选择：原料 8/30 到，批次不得显示 8/25 开工。
            # 材料时间未知（None）时给机台临时排期，但 ETA 不可靠。
            earliest_start=material_available,
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
                resource["rate"] * calendar.working_span(resource["start"], common_finish)
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
        _allocate_supply(db, calendar, runs, demands)
        reliable = (
            product_id not in shortage_products
            and product_id not in missing_bom_products
        )
        if product_id in missing_bom_products:
            note = "产品未配置 BOM；机器排程 ETA 仅供参考，暂不可承诺"
        elif product_id in shortage_products:
            note = "理论机台排期：原材料不足（现有库存加预计到货仍无法覆盖），暂不可承诺"
        elif material_available is not None and material_available > now:
            note = f"原材料在途，预计 {material_available:%m-%d} 到货后可排产"
            for demand in demands:
                if demand["line"].estimated_completion_at and demand["line"].estimated_completion_at < material_available:
                    demand["line"].estimated_completion_at = material_available
        else:
            note = ""
        for demand in demands:
            demand["line"].eta_reliable = reliable and bool(
                demand["line"].estimated_completion_at
            )
            demand["line"].eta_note = note or "按当前产能与资源占用模拟"

    # 外协/半成品供给的最终 ETA 合并：一行的完整供给 = 生产部分 + 外协部分，
    # 行 ETA 取两者较晚；含无时间来源的供给（未送出半成品/无预计回厂批次）时
    # 不可靠并给出具体原因。
    for order in active_orders:
        for line in order.items:
            info = pipeline_info.get(line.id)
            if not info or (info["dated"] + info["undated"] + info["semi"]) <= 0:
                continue
            if info["production"] <= 0:
                if info["undated"] > 0 or info["semi"] > 0:
                    line.estimated_completion_at = None
                    line.eta_reliable = False
                    line.eta_note = "半成品待外协送出" if info["semi"] > 0 else "外协在途批次缺少预计回厂时间"
                else:
                    line.estimated_completion_at = info["eta"]
                    line.eta_reliable = bool(info["eta"])
                    line.eta_note = (
                        f"外协在途，预计 {info['eta']:%m-%d} 回厂" if info["eta"] else "外协在途"
                    )
            else:
                if info["eta"] is not None and (
                    line.estimated_completion_at is None or line.estimated_completion_at < info["eta"]
                ):
                    line.estimated_completion_at = info["eta"]
                if info["undated"] > 0 or info["semi"] > 0:
                    line.eta_reliable = False
                    line.eta_note = (
                        (line.eta_note or "")
                        + ("；" if line.eta_note else "")
                        + ("半成品待外协送出" if info["semi"] > 0 else "外协在途批次缺少预计回厂时间")
                    )

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
