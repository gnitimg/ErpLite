"""Stage 4 专项测试：统一未来供给 / 生产日历 / 物料时间轴 / ETA 时间模型。"""
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.main import cancel_order
from app.models import (
    InventoryItem,
    ProductionAllocation,
    ProductionRun,
    ProductionSetting,
    SalesOrder,
    SalesOrderItem,
)
from app.planning import recalculate_production_plan
from app.schemas import OrderCancelPayload


NOW = datetime(2026, 8, 20, 8, 0, 0)


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def make_product(db: Session, sku: str, daily_capacity: int = 1000) -> InventoryItem:
    product = InventoryItem(
        sku=sku, name=sku, kind="PRODUCT", stock_qty=0,
        daily_capacity=daily_capacity, mold_count=1,
    )
    db.add(product)
    db.flush()
    return product


def add_order(
    db: Session,
    order_no: str,
    requirements: list[tuple[InventoryItem, int]],
    days_until_due: int = 5,
) -> SalesOrder:
    order = SalesOrder(
        order_no=order_no,
        customer_name=order_no,
        status="CONFIRMED",
        order_date=date(2026, 8, 20),
        required_date=date(2026, 8, 20) + timedelta(days=days_until_due),
        total_amount=0,
    )
    order.items = [
        SalesOrderItem(
            product_id=product.id,
            quantity=quantity,
            reference_price=1,
            unit_price=1,
            line_total=quantity,
        )
        for product, quantity in requirements
    ]
    db.add(order)
    db.flush()
    return order


def add_setting(db: Session, line_count: int = 1) -> None:
    db.add(ProductionSetting(id=1, line_count=line_count))
    db.flush()


def add_running_run(
    db: Session,
    product: InventoryItem,
    quantity: int,
    line_slot: int = 1,
) -> ProductionRun:
    run = ProductionRun(
        run_no=f"RUN-{product.sku}-{quantity}",
        product_id=product.id,
        planned_quantity=quantity,
        planned_start_at=NOW,
        planned_end_at=NOW + timedelta(days=quantity / max(float(product.daily_capacity), 1)),
        status="RUNNING",
        source_type="ORDER",
        line_slot=line_slot,
        mold_slot=1,
        effective_daily_capacity=product.daily_capacity,
        workflow_version=2,
    )
    db.add(run)
    db.flush()
    return run


def allocate(
    db: Session, run: ProductionRun, order: SalesOrder, quantity: int, sequence: int = 1
) -> ProductionAllocation:
    allocation = ProductionAllocation(
        production_run_id=run.id,
        order_item_id=order.items[0].id,
        quantity=quantity,
        sequence=sequence,
        estimated_completion_at=run.planned_end_at,
    )
    db.add(allocation)
    db.flush()
    return allocation


def all_runs(db: Session) -> list[ProductionRun]:
    return db.scalars(select(ProductionRun)).all()


# ───────────────── 4B：统一 Fixed Run Future Supply ─────────────────

def test_locked_order_run_free_supply_covers_new_demand():
    """CASE 1：锁定 ORDER run 1000（A600+B400），A 取消 keep_runs → 新需求 600 复用空余，不建新批次。"""
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01")
        order_a = add_order(db, "SO-A", [(product, 600)], days_until_due=3)
        order_b = add_order(db, "SO-B", [(product, 400)], days_until_due=5)
        recalculate_production_plan(db, NOW)
        assert len(all_runs(db)) == 1
        all_runs(db)[0].schedule_locked = True
        db.flush()

        cancel_order(order_a.id, OrderCancelPayload(disposition="keep_runs"), db)
        db.expire_all()
        kept = all_runs(db)[0]
        assert int(kept.planned_quantity) == 1000
        assert sum(int(a.quantity) for a in kept.allocations) == 400

        order_c = add_order(db, "SO-C", [(product, 600)], days_until_due=7)
        recalculate_production_plan(db, NOW)
        db.expire_all()
        runs = all_runs(db)
        assert len(runs) == 1, "空余 600 必须复用固定批次，不得新建 ProductionRun"
        assert sorted(int(a.quantity) for a in runs[0].allocations) == [400, 600]
        db.refresh(order_c.items[0])
        assert order_c.items[0].estimated_completion_at == runs[0].planned_end_at


def test_running_run_free_supply_covers_new_demand():
    """CASE 2：RUNNING run 1000 已分配 700 → 新需求 300 全部来自剩余产能。"""
    with database() as db:
        add_setting(db, line_count=2)
        product = make_product(db, "P01")
        order_a = add_order(db, "SO-A", [(product, 700)])
        run = add_running_run(db, product, 1000)
        allocate(db, run, order_a, 700)
        order_b = add_order(db, "SO-B", [(product, 300)], days_until_due=6)

        recalculate_production_plan(db, NOW)
        db.expire_all()
        assert len(all_runs(db)) == 1, "RUNNING 剩余 300 足以覆盖新需求，不得新建批次"
        db.refresh(order_b.items[0])
        assert order_b.items[0].estimated_completion_at == run.planned_end_at
        assert order_b.items[0].eta_reliable


def test_running_free_supply_partial_then_new_run_for_remainder():
    """CASE 3：RUNNING 空余 200，新需求 500 → 200 来自 RUNNING，只新排 300。"""
    with database() as db:
        add_setting(db, line_count=2)
        product = make_product(db, "P01")
        order_a = add_order(db, "SO-A", [(product, 800)])
        run = add_running_run(db, product, 1000)
        allocate(db, run, order_a, 800)
        order_b = add_order(db, "SO-B", [(product, 500)], days_until_due=6)

        recalculate_production_plan(db, NOW)
        db.expire_all()
        runs = all_runs(db)
        assert len(runs) == 2
        allocated_to_b = sum(
            int(a.quantity)
            for a in runs[0].allocations
            if a.production_run_id == run.id and a.order_item_id == order_b.items[0].id
        )
        assert allocated_to_b == 200
        new_runs = [r for r in runs if r.id != run.id]
        assert len(new_runs) == 1
        assert int(new_runs[0].planned_quantity) == 300


def test_free_supply_never_crosses_products():
    """CASE 4：P01 的空余供给不能喂给 P02 的需求。"""
    with database() as db:
        add_setting(db, line_count=2)
        p01 = make_product(db, "P01")
        p02 = make_product(db, "P02")
        order_a = add_order(db, "SO-A", [(p01, 300)])
        run = add_running_run(db, p01, 1000, line_slot=1)
        allocate(db, run, order_a, 300)
        order_b = add_order(db, "SO-B", [(p02, 600)])

        recalculate_production_plan(db, NOW)
        db.expire_all()
        runs = all_runs(db)
        assert len(runs) == 2
        p02_runs = [r for r in runs if r.product_id == p02.id]
        assert len(p02_runs) == 1 and int(p02_runs[0].planned_quantity) == 600
        assert not [a for a in runs[0].allocations if a.order_item_id == order_b.items[0].id]


# ───────────────── 4C：生产日历 ─────────────────

def add_calendar_exception(db, day, is_working_day, note=""):
    from app.models import ProductionCalendarException
    row = ProductionCalendarException(exception_date=day, is_working_day=is_working_day, note=note)
    db.add(row)
    db.flush()
    return row


# NOW 是周四 2026-08-20 08:00；8/22(六)、8/23(日)休息。
def test_two_production_days_from_thursday_end_monday():
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01")
        add_order(db, "SO-1", [(product, 2000)])
        recalculate_production_plan(db, NOW)
        run = all_runs(db)[0]
        # 周四 + 周五两个生产日，结束落在周一同时刻，不把周末计入产能
        assert run.planned_start_at == NOW
        assert run.planned_end_at == datetime(2026, 8, 24, 8, 0)


def test_working_saturday_exception_contributes_capacity():
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01")
        order1 = add_order(db, "SO-1", [(product, 2000)])
        recalculate_production_plan(db, NOW)
        assert all_runs(db)[0].planned_end_at == datetime(2026, 8, 24, 8, 0)
        # 周六调班生产后重排：周四+周五完成 2 天任务，结束落在周六（调班日）同时刻
        order1.status = "CANCELLED"
        db.flush()
        add_calendar_exception(db, date(2026, 8, 22), True, "调班")
        order2 = add_order(db, "SO-2", [(product, 2000)], days_until_due=6)
        recalculate_production_plan(db, NOW)
        db.expire_all()
        active = [r for r in all_runs(db) if r.status == "PLANNED"]
        assert active[0].planned_end_at == datetime(2026, 8, 22, 8, 0)


def test_resting_wednesday_exception_skips_capacity():
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01")
        add_calendar_exception(db, date(2026, 8, 21), False, "厂休")
        add_order(db, "SO-1", [(product, 1000)])
        recalculate_production_plan(db, NOW)
        run = all_runs(db)[0]
        # 周四开工但周五被例外置为休息：1 个生产日落到下周一
        assert run.planned_end_at == datetime(2026, 8, 24, 8, 0)


def test_working_weekdays_change_recalculates_plan():
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01")
        add_order(db, "SO-1", [(product, 2000)])
        recalculate_production_plan(db, NOW)
        assert all_runs(db)[0].planned_end_at == datetime(2026, 8, 24, 8, 0)
        # 改成 7 天工作制：周四+周五连续，周五完成
        setting = db.get(ProductionSetting, 1)
        setting.working_weekdays = "1,2,3,4,5,6,7"
        db.flush()
        recalculate_production_plan(db, NOW)
        db.expire_all()
        # 7 天工作制：周四+周五连续产出，结束落在周六同时刻（与连续时间模型一致）
        assert all_runs(db)[0].planned_end_at == datetime(2026, 8, 22, 8, 0)


def test_manual_drag_end_respects_calendar():
    with database() as db:
        from app.main import update_production_run_schedule
        from app.schemas import ProductionRunSchedulePayload
        add_setting(db, line_count=1)
        product = make_product(db, "P01")
        add_order(db, "SO-1", [(product, 1000)])
        recalculate_production_plan(db, NOW)
        run = all_runs(db)[0]
        # 拖到（未来的）某个周五 22:00 开始，1 个生产日 → 跳过周末落到周一 22:00
        today = date.today()
        days_until_friday = (4 - today.weekday()) % 7 or 7
        friday_night = datetime.combine(today + timedelta(days=days_until_friday), time(22, 0))
        monday_night = datetime.combine(today + timedelta(days=days_until_friday + 3), time(22, 0))
        update_production_run_schedule(
            run.id,
            ProductionRunSchedulePayload(line_slot=1, planned_start_at=friday_night),
            db,
        )
        db.expire_all()
        assert run.planned_end_at == monday_night


# ───────────────── 4D：Run-Level Material Timeline ─────────────────

def make_part(db, sku, stock=0):
    from app.models import InventoryItem as Item
    part = Item(sku=sku, name=sku, kind="PART", stock_qty=stock)
    db.add(part)
    db.flush()
    return part


def add_bom(db, product, part, quantity):
    from app.models import ProductBomItem
    db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=quantity))
    db.flush()


def add_commitment(db, part, quantity, arrival: datetime, status="PLANNED"):
    from app.models import PurchaseCommitment
    row = PurchaseCommitment(
        part_id=part.id, quantity=quantity,
        expected_arrival_at=arrival, status=status,
        supplier_text="sup", notes="",
    )
    db.add(row)
    db.flush()
    return row


def test_shared_part_stock_first_demand_wins_and_second_waits():
    """X 库存 100：先排的 P01 用 80 立即生产；P02 需 80 只剩 20，等 8/30 的 60 件到货。"""
    with database() as db:
        add_setting(db, line_count=2)
        part = make_part(db, "X", stock=100)
        p01 = make_product(db, "P01", daily_capacity=80)
        p02 = make_product(db, "P02", daily_capacity=80)
        add_bom(db, p01, part, 1)
        add_bom(db, p02, part, 1)
        add_commitment(db, part, 60, datetime(2026, 8, 30, 8, 0))
        order_a = add_order(db, "SO-A", [(p01, 80)], days_until_due=2)
        order_b = add_order(db, "SO-B", [(p02, 80)], days_until_due=3)
        recalculate_production_plan(db, NOW)
        # P01：现有库存覆盖，ETA 就是机台完工时间（周四+1 生产日=周五）
        assert order_a.items[0].estimated_completion_at == NOW + timedelta(days=1)
        assert order_a.items[0].eta_reliable
        # P02：只剩 20 + 60 在途 → 必须等 8/30，ETA 不得早于到货时间
        assert order_b.items[0].estimated_completion_at >= datetime(2026, 8, 30, 8, 0)
        assert "8-30" in (order_b.items[0].eta_note or "")


def test_material_available_runs_out_notes_shortage():
    """库存加承诺都不够：ETA 不可靠且注明供给不足，不伪造可靠时间。"""
    with database() as db:
        add_setting(db, line_count=1)
        part = make_part(db, "X", stock=10)
        p01 = make_product(db, "P01")
        add_bom(db, p01, part, 1)
        add_commitment(db, part, 20, datetime(2026, 8, 26, 8, 0))
        order = add_order(db, "SO-A", [(p01, 100)])
        result = recalculate_production_plan(db, NOW)
        assert result["material_shortage_product_ids"] == [p01.id]
        assert order.items[0].eta_reliable is False
        assert "不足" in (order.items[0].eta_note or "")


def test_arrived_and_cancelled_commitments_do_not_count():
    """ARRIVED 已反映在真实库存、CANCELLED 忽略：只有 PLANNED 参与未来供给。"""
    with database() as db:
        add_setting(db, line_count=1)
        part = make_part(db, "X", stock=0)
        p01 = make_product(db, "P01")
        add_bom(db, p01, part, 1)
        add_commitment(db, part, 50, datetime(2026, 8, 25, 8, 0), status="ARRIVED")
        add_commitment(db, part, 50, datetime(2026, 8, 26, 8, 0), status="CANCELLED")
        add_commitment(db, part, 30, datetime(2026, 8, 28, 8, 0), status="PLANNED")
        order = add_order(db, "SO-A", [(p01, 40)])
        result = recalculate_production_plan(db, NOW)
        # 只有 8/28 的 30 件有效：40 的需求仍缺 10 → shortage
        assert result["material_shortage_product_ids"] == [p01.id]


# ───────────────── 4E：采购预计真正推迟 Run 起点 ─────────────────

def test_material_arrival_pushes_run_start():
    """材料 8/30 到货：批次起点必须是 8/30，不再是“先排 8/25 再 patch ETA”。"""
    with database() as db:
        add_setting(db, line_count=1)
        part = make_part(db, "X", stock=0)
        p01 = make_product(db, "P01", daily_capacity=80)
        add_bom(db, p01, part, 1)
        add_commitment(db, part, 80, datetime(2026, 8, 30, 8, 0))
        order = add_order(db, "SO-A", [(p01, 80)], days_until_due=2)
        recalculate_production_plan(db, NOW)
        run = all_runs(db)[0]
        # 8/30 是周日：起点吸附到周一 8/31，1 个生产日落到周二 08:00；
        # 甘特图与订单 ETA 来自同一时间事实
        assert run.planned_start_at == datetime(2026, 8, 31, 8, 0)
        assert run.planned_end_at == datetime(2026, 9, 1, 8, 0)
        assert order.items[0].estimated_completion_at == datetime(2026, 9, 1, 8, 0)
        assert order.items[0].eta_reliable


def test_unknown_material_gives_provisional_schedule_with_note():
    """材料时间未知：仍给出机台临时排期，但 ETA 不可靠且说明原因。"""
    with database() as db:
        add_setting(db, line_count=1)
        part = make_part(db, "X", stock=0)
        p01 = make_product(db, "P01", daily_capacity=80)
        add_bom(db, p01, part, 1)
        order = add_order(db, "SO-A", [(p01, 80)])
        result = recalculate_production_plan(db, NOW)
        assert result["material_shortage_product_ids"] == [p01.id]
        run = all_runs(db)[0]
        # 机台临时排期仍从现在起（周四+1 生产日=周五），但不可承诺
        assert run.planned_start_at == NOW
        assert run.planned_end_at == NOW + timedelta(days=1)
        assert order.items[0].eta_reliable is False
        assert "理论机台排期" in (order.items[0].eta_note or "")


# ───────────────── 4F：外协 Timeline ─────────────────

def make_ext_batch(db, product, quantity, expected_return_at=None, returned=0, batch_no="EP-1"):
    from app.models import ExternalProcessingBatch, StockTransaction
    tx = StockTransaction(
        transaction_no=f"{batch_no}-TX",
        transaction_type="PROCESS_OUT",
        occurred_at=NOW,
        notes="",
        status="POSTED",
    )
    db.add(tx)
    db.flush()
    batch = ExternalProcessingBatch(
        batch_no=batch_no,
        product_id=product.id,
        process_name_snapshot="喷漆",
        supplier="外协厂",
        quantity=quantity,
        returned_quantity=returned,
        outbound_transaction_id=tx.id,
        sent_at=NOW,
        expected_return_at=expected_return_at,
        notes="",
    )
    db.add(batch)
    db.flush()
    return batch


def test_external_batches_allocated_by_time_per_order():
    """Batch A 50@8/25、B 100@8/30：订单1×40 → 8/25；订单2×80 → 前10来自A、70来自B → 8/30。"""
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01", daily_capacity=100)
        product.requires_external_processing = True
        product.external_process_name = "喷漆"
        make_ext_batch(db, product, 50, datetime(2026, 8, 25, 8, 0), batch_no="EP-A")
        make_ext_batch(db, product, 100, datetime(2026, 8, 30, 8, 0), batch_no="EP-B")
        order1 = add_order(db, "SO-1", [(product, 40)], days_until_due=2)
        order2 = add_order(db, "SO-2", [(product, 80)], days_until_due=3)
        recalculate_production_plan(db)
        assert order1.items[0].pipeline_quantity == 40
        assert order1.items[0].estimated_completion_at == datetime(2026, 8, 25, 8, 0)
        assert order1.items[0].eta_reliable
        assert order2.items[0].pipeline_quantity == 80
        assert order2.items[0].estimated_completion_at == datetime(2026, 8, 30, 8, 0)
        assert order2.items[0].eta_reliable
        # 全部由在途覆盖：不创建生产批次
        assert all_runs(db) == []


def test_pipeline_full_coverage_with_partial_return_keeps_eta():
    """部分回厂后：已回部分成为成品库存（被预留），剩余按 expected_return_at 供 ETA。"""
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01", daily_capacity=100)
        product.requires_external_processing = True
        product.external_process_name = "喷漆"
        # 100 件送出、已回 40（进入成品库存），剩 60 预计 8/30 回厂
        make_ext_batch(db, product, 100, datetime(2026, 8, 30, 8, 0), returned=40, batch_no="EP-C")
        product.stock_qty = 40
        product.processing_qty = 60
        order = add_order(db, "SO-1", [(product, 100)], days_until_due=4)
        recalculate_production_plan(db)
        line = order.items[0]
        # 40 由成品库存预留，60 由外协在途覆盖，ETA = 8/30
        assert int(line.reserved_quantity) == 40
        assert line.pipeline_quantity == 60
        assert line.estimated_completion_at == datetime(2026, 8, 30, 8, 0)
        assert line.eta_reliable


def test_undated_batch_and_semi_finished_make_eta_unreliable():
    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01", daily_capacity=100)
        product.requires_external_processing = True
        product.external_process_name = "喷漆"
        make_ext_batch(db, product, 30, None, batch_no="EP-U")
        order1 = add_order(db, "SO-1", [(product, 30)], days_until_due=2)
        recalculate_production_plan(db)
        # 无预计回厂时间：数量被覆盖但 ETA 不可靠
        assert order1.items[0].pipeline_quantity == 30
        assert order1.items[0].eta_reliable is False
        assert "缺少预计回厂时间" in (order1.items[0].eta_note or "")

        product2 = make_product(db, "P02", daily_capacity=100)
        product2.requires_external_processing = True
        product2.external_process_name = "电镀"
        product2.semi_finished_qty = 20
        order2 = add_order(db, "SO-2", [(product2, 20)], days_until_due=3)
        recalculate_production_plan(db)
        # 半成品未送出：不可交付，ETA 不可靠
        assert order2.items[0].pipeline_quantity == 20
        assert order2.items[0].eta_reliable is False
        assert "半成品待外协送出" in (order2.items[0].eta_note or "")


def test_send_with_explicit_return_date_wins():
    from app.main import send_external_processing
    from app.schemas import ExternalProcessingSendPayload

    with database() as db:
        add_setting(db, line_count=1)
        product = make_product(db, "P01", daily_capacity=100)
        product.requires_external_processing = True
        product.external_process_name = "喷漆"
        product.default_external_lead_days = 5
        product.semi_finished_qty = 50
        db.flush()
        batch = send_external_processing(
            ExternalProcessingSendPayload(
                product_id=product.id,
                quantity=20,
                lead_days=9,
                expected_return_at=datetime(2026, 8, 27, 8, 0),
            ),
            db,
        )
        assert batch["expected_return_at"] == "2026-08-27T08:00:00"


# ───────────────── 4G：最终 ETA 汇总 ─────────────────

def test_second_commitment_lot_sets_material_eta():
    """库存 20 + 两批到货（30@8/25、30@8/26）：80 的需求要等到第二批 8/26。"""
    with database() as db:
        add_setting(db, line_count=1)
        part = make_part(db, "X", stock=20)
        p01 = make_product(db, "P01", daily_capacity=80)
        add_bom(db, p01, part, 1)
        add_commitment(db, part, 30, datetime(2026, 8, 25, 8, 0))
        add_commitment(db, part, 30, datetime(2026, 8, 26, 8, 0))
        order = add_order(db, "SO-A", [(p01, 80)], days_until_due=2)
        recalculate_production_plan(db, NOW)
        run = all_runs(db)[0]
        # 材料可满足时间是 8/26（周三），批次起点不得早于它
        assert run.planned_start_at == datetime(2026, 8, 26, 8, 0)
        assert "08-26" in (order.items[0].eta_note or "")
        assert order.items[0].eta_reliable


def test_partial_stock_plus_production_combined_eta():
    """成品库存 30 立即预留，剩余 70 进入生产：行 ETA = 生产完工时间。"""
    with database() as db:
        add_setting(db, line_count=1)
        part = make_part(db, "X", stock=1000)
        product = make_product(db, "P01", daily_capacity=70)
        product.stock_qty = 30
        add_bom(db, product, part, 1)
        order = add_order(db, "SO-A", [(product, 100)])
        recalculate_production_plan(db, NOW)
        line = order.items[0]
        assert int(line.reserved_quantity) == 30
        run = all_runs(db)[0]
        assert int(run.planned_quantity) == 70
        # 30 件随时可发，70 件周五完工 → 行 ETA = 周五，且可承诺
        assert line.estimated_completion_at == run.planned_end_at == NOW + timedelta(days=1)
        assert line.eta_reliable


def test_order_eta_is_max_of_lines():
    """订单 ETA = 各行 ETA 的最大值。"""
    with database() as db:
        add_setting(db, line_count=2)
        part = make_part(db, "X", stock=1000)
        fast = make_product(db, "P-FAST", daily_capacity=100)
        slow = make_product(db, "P-SLOW", daily_capacity=100)
        add_bom(db, fast, part, 1)
        add_bom(db, slow, part, 1)
        order = add_order(db, "SO-A", [(fast, 100), (slow, 200)])
        recalculate_production_plan(db, NOW)
        # fast 1 个生产日 → 周五；slow 2 个生产日跨周末 → 下周一
        assert order.items[0].estimated_completion_at == NOW + timedelta(days=1)
        assert order.items[1].estimated_completion_at == datetime(2026, 8, 24, 8, 0)
        assert order.estimated_completion_at == datetime(2026, 8, 24, 8, 0)
        assert order.eta_reliable
