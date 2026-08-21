from contextlib import asynccontextmanager
import asyncio
from datetime import date, datetime, time, timedelta
import json
import logging
import os
from pathlib import Path
import sys
from typing import Literal

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    __package__ = "app"

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import and_, func, or_, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from .backup import BackupError, create_backup_archive, list_backup_archives, resolve_backup_file, restore_backup_archive
from .database import SessionLocal, engine, get_db, run_migrations
from .models import (
    InventoryItem,
    OperationLog,
    ProductBomItem,
    ProductionCapability,
    ProductionRun,
    ProductionSetting,
    SalesOrder,
    SalesOrderItem,
    StockTransaction,
    StockTransactionItem,
)
from .schemas import (
    BackupRestorePayload,
    LoginPayload,
    OrderPayload,
    OrderStockPayload,
    PartPayload,
    ProductPayload,
    ProductionCapabilityPayload,
    ProductionRunSchedulePayload,
    ProductionRunStatusPayload,
    ProductionSettingsPayload,
    SamplePayload,
    StockPayload,
)
from .planning import list_production_runs, recalculate_production_plan
from .services import (
    create_transaction,
    client_ip,
    ensure_sku_available,
    item_dict,
    load_order,
    operation_log_dict,
    order_dict,
    order_workflow_dict,
    rebalance_product_reservations,
    release_order_reservations,
    reserved_product_quantity,
    seed_demo,
    serial,
    transaction_dict,
)


StockStatus = Literal["LOW", "NORMAL"]
BomStatus = Literal["CONFIGURED", "EMPTY"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    try:
        run_migrations()
        if os.getenv("ERP_SEED_DEMO", "0").strip().lower() in {"1", "true", "yes"}:
            with SessionLocal() as db:
                seed_demo(db)
        _app.state.database_ready = True
    except SQLAlchemyError as error:
        _app.state.database_ready = False
        logging.getLogger("uvicorn.error").warning("MySQL is not ready; ERP data APIs are temporarily unavailable: %s", error)
    yield


app = FastAPI(title="轻量 ERP API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3333", "http://127.0.0.1:3333", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChangeEventHub:
    """向当前进程中的浏览器连接广播轻量数据变更事件。"""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[str]] = set()
        self._sequence = 0

    def subscribe(self) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=20)
        self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._queues.discard(queue)

    def publish(self, *, path: str, method: str, source: str) -> None:
        self._sequence += 1
        payload = json.dumps(
            {
                "id": self._sequence,
                "path": path,
                "method": method,
                "source": source,
                "occurred_at": datetime.now().isoformat(),
            },
            ensure_ascii=False,
        )
        for queue in tuple(self._queues):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(payload)


change_events = ChangeEventHub()


@app.middleware("http")
async def broadcast_successful_writes(request: Request, call_next):
    response = None
    error = None
    try:
        response = await call_next(request)
    except Exception as caught:
        error = caught
    is_write = request.method in {"POST", "PUT", "PATCH", "DELETE"}
    is_business_api = request.url.path.startswith("/api/")
    is_log_api = request.url.path.startswith("/api/operation-logs")
    is_login = request.url.path == "/api/v1/auth/login"
    if is_write and is_business_api and not is_log_api:
        status_code = response.status_code if response else 500
        try:
            with SessionLocal() as audit_db:
                audit_db.add(OperationLog(
                    username=request.headers.get("x-erp-operator", "仓库管理员")[:120],
                    action=operation_action(request.url.path, request.method),
                    target=request.url.path[:255],
                    method=request.method,
                    path=request.url.path[:255],
                    ip_address=client_ip(request)[:64],
                    status="SUCCESS" if status_code < 400 else "FAILED",
                    detail=f"HTTP {status_code}",
                ))
                audit_db.commit()
        except Exception as audit_error:
            logging.getLogger("uvicorn.error").warning("记录操作日志失败: %s", audit_error)
        if status_code < 400 and not is_login:
            change_events.publish(
                path=request.url.path,
                method=request.method,
                source=request.headers.get("x-erp-client-id", ""),
            )
    if error:
        raise error
    return response


def operation_action(path: str, method: str) -> str:
    if path == "/api/v1/auth/login":
        return "登录"
    if path == "/api/stock/inbound":
        return "物料入库"
    if path == "/api/stock/outbound":
        return "物料出库"
    if path.startswith("/api/orders"):
        if path.endswith("/confirm"):
            return "确认客单"
        if path.endswith("/prepare"):
            return "客单备货"
        if path.endswith("/receive-materials"):
            return "客单补料"
        if path.endswith("/fulfill"):
            return "客单出库"
        if path.endswith("/cancel"):
            return "取消客单"
        return "新建客单"
    if path.startswith("/api/parts"):
        return {"POST": "新建零件", "PUT": "编辑零件", "DELETE": "停用零件"}.get(
            method, "零件目录"
        )
    if path.startswith("/api/products"):
        return {"POST": "新建产品", "PUT": "编辑产品", "DELETE": "停用产品"}.get(
            method, "产品目录"
        )
    if path.startswith("/api/samples"):
        return "调整样品库存"
    if path.startswith("/api/production/plan"):
        return "重算生产计划"
    if path.startswith("/api/production/runs"):
        if path.endswith("/schedule"):
            return "调整订单排产"
        return "更新生产批次"
    if path.startswith("/api/system/production-settings"):
        return "修改生产设置"
    if path.startswith("/api/production/capabilities"):
        return "维护生产能力"
    if path.startswith("/api/backups"):
        return "恢复数据备份" if path.endswith("/restore") else "创建数据备份"
    return f"{method} 操作"


@app.get("/api/operation-logs")
def operation_logs(
    keyword: str = "",
    username: str = "",
    action: str = "",
    status: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    query = select(OperationLog)
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(or_(
            OperationLog.action.ilike(token),
            OperationLog.target.ilike(token),
            OperationLog.detail.ilike(token),
            OperationLog.path.ilike(token),
        ))
    if username.strip():
        query = query.where(OperationLog.username == username.strip())
    if action.strip():
        query = query.where(OperationLog.action == action.strip())
    if status.strip():
        query = query.where(OperationLog.status == status.strip())
    if start_date:
        query = query.where(OperationLog.created_at >= datetime.combine(start_date, time.min))
    if end_date:
        query = query.where(OperationLog.created_at <= datetime.combine(end_date, time.max))
    rows = db.scalars(
        query.order_by(OperationLog.created_at.desc(), OperationLog.id.desc()).limit(limit)
    ).all()
    return [operation_log_dict(row) for row in rows]


@app.get("/api/operation-logs/actions")
def operation_log_actions(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(OperationLog.action)
        .where(OperationLog.action != "")
        .distinct()
        .order_by(OperationLog.action)
    ).all()
    return list(rows)


@app.exception_handler(SQLAlchemyError)
async def database_error_handler(_request, _error):
    return JSONResponse(status_code=503, content={"detail": "MySQL 数据库尚未就绪，请先启动本机数据库"})


def find_item(db: Session, item_id: int, kind: str | None = None) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if not item or not item.active or (kind and item.kind != kind):
        raise HTTPException(404, "物料不存在")
    return item


def list_items(
    db: Session,
    kind: str,
    keyword: str = "",
    include_bom: bool = False,
    stock_status: StockStatus | None = None,
    bom_status: BomStatus | None = None,
    supply_mode: Literal["STOCK", "BUY_TO_ORDER"] | None = None,
) -> list[dict]:
    query = select(InventoryItem).where(InventoryItem.kind == kind, InventoryItem.active.is_(True))
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(
            or_(InventoryItem.sku.ilike(token), InventoryItem.name.ilike(token), InventoryItem.spec.ilike(token))
        )
    if stock_status == "LOW":
        query = query.where(InventoryItem.stock_qty <= InventoryItem.min_stock)
    elif stock_status == "NORMAL":
        query = query.where(InventoryItem.stock_qty > InventoryItem.min_stock)
    if bom_status == "CONFIGURED":
        query = query.where(InventoryItem.bom_components.any())
    elif bom_status == "EMPTY":
        query = query.where(~InventoryItem.bom_components.any())
    if kind == "PART" and supply_mode:
        query = query.where(InventoryItem.supply_mode == supply_mode)
    if include_bom:
        query = query.options(selectinload(InventoryItem.bom_components).selectinload(ProductBomItem.part))
    items = db.scalars(query.order_by(InventoryItem.id.desc())).all()
    rows = []
    for item in items:
        data = item_dict(item, include_bom)
        reserved = reserved_product_quantity(db, item.id) if item.kind == "PRODUCT" else 0
        data["reserved_qty"] = reserved
        data["available_qty"] = max(float(item.stock_qty) - reserved, 0)
        rows.append(data)
    return rows


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "lite-erp", "database": "ready" if getattr(app.state, "database_ready", False) else "unavailable"}


@app.get("/api/events")
async def data_change_events(request: Request):
    async def stream():
        queue = change_events.subscribe()
        try:
            yield "retry: 3000\n\n"
            while not await request.is_disconnected():
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    yield f"event: data-change\ndata: {payload}\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            change_events.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/v1/auth/login")
def login(payload: LoginPayload):
    username = os.getenv("ERP_ADMIN_USER", "admin")
    password = os.getenv("ERP_ADMIN_PASSWORD", "12345678")
    if payload.username != username or payload.password != password:
        raise HTTPException(401, "用户名或密码错误")
    return {"code": 0, "data": {"token": "lite-erp-local-admin"}, "message": "success"}


@app.get("/api/v1/users/me")
def current_user():
    return {"code": 0, "data": {"username": "仓库管理员", "roles": ["admin"], "permissions": []}, "message": "success"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    active = InventoryItem.active.is_(True)
    regular_inventory = InventoryItem.kind.in_(["PART", "PRODUCT"])
    part_count = db.scalar(select(func.count()).select_from(InventoryItem).where(active, InventoryItem.kind == "PART")) or 0
    product_count = db.scalar(select(func.count()).select_from(InventoryItem).where(active, InventoryItem.kind == "PRODUCT")) or 0
    low_stock = db.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(active, regular_inventory, InventoryItem.stock_qty <= InventoryItem.min_stock)
    ) or 0
    pending_orders = db.scalar(
        select(func.count())
        .select_from(SalesOrder)
        .where(SalesOrder.status.in_([
            "DRAFT", "CONFIRMED", "WAITING_MATERIALS", "READY_TO_SHIP"
        ]))
    ) or 0
    inventory_value = db.scalar(
        select(func.sum(InventoryItem.stock_qty * InventoryItem.cost_price)).where(active, regular_inventory)
    ) or 0
    recent_txs = db.scalars(
        select(StockTransaction)
        .options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item), selectinload(StockTransaction.related_order))
        .order_by(StockTransaction.occurred_at.desc()).limit(6)
    ).all()
    low_items = db.scalars(
        select(InventoryItem)
        .where(active, regular_inventory, InventoryItem.stock_qty <= InventoryItem.min_stock)
        .order_by(InventoryItem.stock_qty)
    ).all()
    pending_order_rows = db.scalars(
        select(SalesOrder)
        .where(SalesOrder.status.in_(["CONFIRMED", "WAITING_MATERIALS", "READY_TO_SHIP"]))
        .options(
            selectinload(SalesOrder.items)
            .selectinload(SalesOrderItem.product)
            .selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part)
        )
        .order_by(SalesOrder.required_date, SalesOrder.order_date, SalesOrder.id)
    ).all()
    purchase_todos: list[dict] = []
    production_todos: list[dict] = []
    shipping_todos: list[dict] = []
    for order in pending_order_rows:
        workflow = order_workflow_dict(db, order)
        todo = {
            "order_id": order.id,
            "order_no": order.order_no,
            "customer_name": order.customer_name,
            "required_date": (order.required_date or order.order_date).isoformat(),
        }
        shortages = [row for row in workflow["material_lines"] if row["shortage_quantity"] > 1e-9]
        if workflow["next_action"] == "PURCHASE":
            purchase_todos.append({**todo, "lines": shortages})
        elif workflow["next_action"] == "PRODUCE":
            production_todos.append(
                {**todo, "lines": [row for row in workflow["product_lines"] if row["production_required"] > 1e-9]}
            )
        elif workflow["next_action"] == "SHIP":
            shipping_todos.append({**todo, "lines": workflow["product_lines"]})

    return {
        "metrics": {
            "parts": part_count,
            "products": product_count,
            "low_stock": low_stock,
            "pending_orders": pending_orders,
            "inventory_value": inventory_value,
        },
        "recent_transactions": [transaction_dict(tx) for tx in recent_txs],
        "low_stock_items": [item_dict(item) for item in low_items[:8]],
        "todos": {
            "purchase": purchase_todos,
            "production": production_todos,
            "shipping": shipping_todos,
        },
    }


@app.get("/api/parts")
def parts(
    keyword: str = "",
    stock_status: StockStatus | None = None,
    supply_mode: Literal["STOCK", "BUY_TO_ORDER"] | None = None,
    db: Session = Depends(get_db),
):
    return list_items(db, "PART", keyword, stock_status=stock_status, supply_mode=supply_mode)


@app.post("/api/parts", status_code=201)
def create_part(payload: PartPayload, db: Session = Depends(get_db)):
    ensure_sku_available(db, payload.sku)
    item = InventoryItem(kind="PART", sale_price=0, stock_qty=0, **payload.model_dump())
    item.sku = item.sku.upper()
    db.add(item)
    db.commit()
    db.refresh(item)
    return item_dict(item)


@app.put("/api/parts/{item_id}")
def update_part(item_id: int, payload: PartPayload, db: Session = Depends(get_db)):
    item = find_item(db, item_id, "PART")
    ensure_sku_available(db, payload.sku, item_id)
    for key, value in payload.model_dump().items():
        setattr(item, key, value)
    item.sku = item.sku.upper()
    db.commit()
    return item_dict(item)


@app.delete("/api/parts/{item_id}")
def delete_part(item_id: int, db: Session = Depends(get_db)):
    item = find_item(db, item_id, "PART")
    if db.scalar(select(ProductBomItem.id).where(ProductBomItem.part_id == item_id).limit(1)):
        raise HTTPException(409, "该零件已用于产品 BOM，不能停用")
    item.active = False
    db.commit()
    return {"ok": True}


@app.get("/api/samples")
def samples(keyword: str = "", db: Session = Depends(get_db)):
    query = select(InventoryItem).where(
        InventoryItem.kind == "PRODUCT",
        InventoryItem.active.is_(True),
    )
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(
            or_(
                InventoryItem.sku.ilike(token),
                InventoryItem.name.ilike(token),
                InventoryItem.spec.ilike(token),
            )
        )
    products = db.scalars(query.order_by(InventoryItem.sku)).all()
    return [item_dict(product) for product in products]


@app.put("/api/samples/{item_id}")
def update_sample(
    item_id: int,
    payload: SamplePayload,
    db: Session = Depends(get_db),
):
    product = find_item(db, item_id, "PRODUCT")
    stock_delta = payload.stock_qty - int(product.sample_stock_qty or 0)
    product.sample_stock_qty = payload.stock_qty
    if stock_delta:
        transaction = StockTransaction(
            transaction_no=serial("ST"),
            transaction_type="SAMPLE_ADJUST",
            notes=f"{product.name} 样品库存调整为 {payload.stock_qty} {product.unit}",
        )
        db.add(transaction)
        db.flush()
        db.add(StockTransactionItem(
            transaction_id=transaction.id,
            item_id=product.id,
            quantity_change=stock_delta,
            unit_cost=0,
        ))
    db.commit()
    db.refresh(product)
    return item_dict(product)


@app.get("/api/products")
def products(
    keyword: str = "",
    stock_status: StockStatus | None = None,
    bom_status: BomStatus | None = None,
    db: Session = Depends(get_db),
):
    return list_items(db, "PRODUCT", keyword, True, stock_status, bom_status)


def save_product(db: Session, payload: ProductPayload, product: InventoryItem | None = None) -> InventoryItem:
    ensure_sku_available(db, payload.sku, product.id if product else None)
    part_ids = [line.part_id for line in payload.components]
    parts = {
        part.id: part
        for part in db.scalars(
            select(InventoryItem).where(
                InventoryItem.id.in_(part_ids),
                InventoryItem.kind == "PART",
                InventoryItem.active.is_(True),
            )
        ).all()
    } if part_ids else {}
    if len(parts) != len(part_ids):
        raise HTTPException(400, "BOM 中包含无效零件")
    values = payload.model_dump(exclude={"components"})
    if product is None:
        product = InventoryItem(kind="PRODUCT", stock_qty=0, **values)
        db.add(product)
        db.flush()
    else:
        for key, value in values.items():
            setattr(product, key, value)
        product.bom_components.clear()
        db.flush()
    product.sku = product.sku.upper()
    product.bom_components = [
        ProductBomItem(part_id=line.part_id, quantity=line.quantity)
        for line in payload.components
    ]
    db.flush()
    recalculate_production_plan(db)
    db.commit()
    return db.scalar(
        select(InventoryItem)
        .where(InventoryItem.id == product.id)
        .options(
            selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part)
        )
    )


@app.post("/api/products", status_code=201)
def create_product(payload: ProductPayload, db: Session = Depends(get_db)):
    try:
        return item_dict(save_product(db, payload), True)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "产品数据冲突")


@app.put("/api/products/{item_id}")
def update_product(item_id: int, payload: ProductPayload, db: Session = Depends(get_db)):
    product = db.scalar(select(InventoryItem).where(InventoryItem.id == item_id).options(selectinload(InventoryItem.bom_components)))
    if not product or product.kind != "PRODUCT" or not product.active:
        raise HTTPException(404, "产品不存在")
    return item_dict(save_product(db, payload, product), True)


@app.delete("/api/products/{item_id}")
def delete_product(item_id: int, db: Session = Depends(get_db)):
    product = find_item(db, item_id, "PRODUCT")
    if db.scalar(select(SalesOrderItem.id).where(SalesOrderItem.product_id == item_id).limit(1)):
        raise HTTPException(409, "该产品已有客单记录，不能停用")
    product.active = False
    db.commit()
    return {"ok": True}


def production_settings_dict(settings: ProductionSetting) -> dict:
    return {
        "line_count": settings.line_count,
        "schedule_auto_snap": settings.schedule_auto_snap,
        "updated_at": settings.updated_at.isoformat(),
    }


def capability_dict(capability: ProductionCapability) -> dict:
    return {
        "id": capability.id,
        "product_id": capability.product_id,
        "product_sku": capability.product.sku,
        "product_name": capability.product.name,
        "mold_count": max(int(capability.product.mold_count or 1), 1),
        "nominal_daily_capacity": capability.nominal_daily_capacity,
        "safety_factor": capability.safety_factor,
        "effective_daily_capacity": round(
            capability.nominal_daily_capacity * capability.safety_factor, 6
        ),
        "active": capability.active,
    }


@app.get("/api/system/production-settings")
def production_settings(db: Session = Depends(get_db)):
    row = db.get(ProductionSetting, 1)
    if row is None:
        row = ProductionSetting(id=1, line_count=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return production_settings_dict(row)


@app.put("/api/system/production-settings")
def update_production_settings(
    payload: ProductionSettingsPayload,
    db: Session = Depends(get_db),
):
    row = db.get(ProductionSetting, 1)
    if row is None:
        row = ProductionSetting(id=1)
        db.add(row)
    row.line_count = payload.line_count
    row.schedule_auto_snap = payload.schedule_auto_snap
    db.flush()
    recalculate_production_plan(db)
    db.commit()
    db.refresh(row)
    return production_settings_dict(row)


def load_capability(db: Session, capability_id: int) -> ProductionCapability:
    row = db.scalar(
        select(ProductionCapability)
        .where(ProductionCapability.id == capability_id)
        .options(
            selectinload(ProductionCapability.product),
        )
    )
    if not row:
        raise HTTPException(404, "生产能力配置不存在")
    return row


@app.get("/api/production/capabilities")
def production_capabilities(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ProductionCapability)
        .options(
            selectinload(ProductionCapability.product),
        )
        .order_by(ProductionCapability.product_id, ProductionCapability.id)
    ).all()
    return [capability_dict(row) for row in rows]


def save_capability(
    db: Session,
    payload: ProductionCapabilityPayload,
    row: ProductionCapability | None = None,
) -> ProductionCapability:
    product = find_item(db, payload.product_id, "PRODUCT")
    duplicate = select(ProductionCapability.id).where(
        ProductionCapability.product_id == product.id,
    )
    if row:
        duplicate = duplicate.where(ProductionCapability.id != row.id)
    if db.scalar(duplicate):
        raise HTTPException(409, "该产品的生产能力配置已存在")
    values = payload.model_dump()
    if row is None:
        row = ProductionCapability(**values, line_id=None, mold_id=None)
        db.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
        row.line_id = None
        row.mold_id = None
    db.flush()
    recalculate_production_plan(db)
    db.commit()
    return load_capability(db, row.id)


@app.post("/api/production/capabilities", status_code=201)
def create_capability(payload: ProductionCapabilityPayload, db: Session = Depends(get_db)):
    return capability_dict(save_capability(db, payload))


@app.put("/api/production/capabilities/{capability_id}")
def update_capability(
    capability_id: int,
    payload: ProductionCapabilityPayload,
    db: Session = Depends(get_db),
):
    return capability_dict(save_capability(db, payload, load_capability(db, capability_id)))


@app.delete("/api/production/capabilities/{capability_id}")
def delete_capability(capability_id: int, db: Session = Depends(get_db)):
    row = load_capability(db, capability_id)
    row.active = False
    recalculate_production_plan(db)
    db.commit()
    return {"ok": True}


@app.get("/api/production/runs")
def production_runs(status: str | None = None, db: Session = Depends(get_db)):
    return list_production_runs(db, status)


@app.post("/api/production/plan/recalculate")
def recalculate_plan(db: Session = Depends(get_db)):
    result = recalculate_production_plan(db)
    db.commit()
    return result


@app.put("/api/production/runs/{run_id}/status")
def update_production_run_status(
    run_id: int,
    payload: ProductionRunStatusPayload,
    db: Session = Depends(get_db),
):
    run = db.get(ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "生产批次不存在")
    if run.status not in {"PLANNED", "RUNNING"}:
        raise HTTPException(409, "该生产批次已结束，不能修改状态")
    run.status = payload.status
    if payload.status == "RUNNING" and run.actual_start_at is None:
        run.actual_start_at = datetime.now()
    if payload.status == "CANCELLED":
        recalculate_production_plan(db)
    db.commit()
    return {"ok": True, "run_id": run_id, "status": run.status}


def _active_schedule_condition():
    return or_(
        ProductionRun.status == "RUNNING",
        and_(
            ProductionRun.status == "PLANNED",
            ProductionRun.schedule_locked.is_(True),
        ),
    )


@app.put("/api/production/runs/{run_id}/schedule")
def update_production_run_schedule(
    run_id: int,
    payload: ProductionRunSchedulePayload,
    db: Session = Depends(get_db),
):
    run = db.scalar(
        select(ProductionRun)
        .where(ProductionRun.id == run_id)
        .options(selectinload(ProductionRun.allocations))
        .with_for_update()
    )
    if not run:
        raise HTTPException(404, "生产批次不存在")
    if run.status != "PLANNED":
        raise HTTPException(409, "只有待生产批次可以调整排期")
    settings = db.get(ProductionSetting, 1)
    line_count = max(int(settings.line_count if settings else 1), 1)
    if payload.line_slot > line_count:
        raise HTTPException(400, "生产位超出系统设置的可用范围")

    planned_start = payload.planned_start_at
    if planned_start.tzinfo is not None:
        planned_start = planned_start.astimezone().replace(tzinfo=None)
    if planned_start < datetime.now() - timedelta(minutes=1):
        raise HTTPException(400, "排产开始时间不能早于当前时间")
    duration_seconds = max(
        float(run.planned_quantity)
        / max(float(run.effective_daily_capacity), 1e-9)
        * 86400,
        60,
    )
    planned_end = planned_start + timedelta(seconds=duration_seconds)

    line_conflict = db.scalar(
        select(ProductionRun.id).where(
            ProductionRun.id != run.id,
            _active_schedule_condition(),
            ProductionRun.line_slot == payload.line_slot,
            ProductionRun.planned_start_at < planned_end,
            ProductionRun.planned_end_at > planned_start,
        ).limit(1)
    )
    if line_conflict:
        raise HTTPException(409, "该生产位在所选时间段已有确认排期")

    mold_count = max(int(run.product.mold_count or 1), 1)
    chosen_mold_slot = None
    preferred_slots = [run.mold_slot] + [
        slot for slot in range(1, mold_count + 1) if slot != run.mold_slot
    ]
    for mold_slot in preferred_slots:
        mold_conflict = db.scalar(
            select(ProductionRun.id).where(
                ProductionRun.id != run.id,
                _active_schedule_condition(),
                ProductionRun.product_id == run.product_id,
                ProductionRun.mold_slot == mold_slot,
                ProductionRun.planned_start_at < planned_end,
                ProductionRun.planned_end_at > planned_start,
            ).limit(1)
        )
        if not mold_conflict:
            chosen_mold_slot = mold_slot
            break
    if chosen_mold_slot is None:
        raise HTTPException(409, "该产品在所选时间段没有可用模具")

    time_shift = planned_start - run.planned_start_at
    run.line_slot = payload.line_slot
    run.mold_slot = chosen_mold_slot
    run.planned_start_at = planned_start
    run.planned_end_at = planned_end
    run.schedule_locked = True
    for allocation in run.allocations:
        if allocation.estimated_completion_at:
            allocation.estimated_completion_at += time_shift
    db.flush()
    recalculate_production_plan(db)
    db.commit()
    return next(
        row for row in list_production_runs(db) if row["id"] == run_id
    )


@app.delete("/api/production/runs/{run_id}/schedule")
def unlock_production_run_schedule(
    run_id: int,
    db: Session = Depends(get_db),
):
    run = db.get(ProductionRun, run_id)
    if not run:
        raise HTTPException(404, "生产批次不存在")
    if run.status != "PLANNED":
        raise HTTPException(409, "只有待生产批次可以恢复自动排期")
    run.schedule_locked = False
    recalculate_production_plan(db)
    db.commit()
    return {"ok": True}


@app.get("/api/inventory")
def inventory(
    kind: str | None = None,
    low_stock: bool = False,
    stock_status: StockStatus | None = None,
    keyword: str = "",
    db: Session = Depends(get_db),
):
    query = select(InventoryItem).where(
        InventoryItem.active.is_(True),
        InventoryItem.kind.in_(["PART", "PRODUCT"]),
    )
    if kind in {"PART", "PRODUCT"}:
        query = query.where(InventoryItem.kind == kind)
    if stock_status == "LOW" or (stock_status is None and low_stock):
        query = query.where(InventoryItem.stock_qty <= InventoryItem.min_stock)
    elif stock_status == "NORMAL":
        query = query.where(InventoryItem.stock_qty > InventoryItem.min_stock)
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(
            or_(InventoryItem.sku.ilike(token), InventoryItem.name.ilike(token), InventoryItem.spec.ilike(token))
        )
    items = db.scalars(query.order_by(InventoryItem.kind, InventoryItem.sku)).all()
    rows = []
    for item in items:
        data = item_dict(item)
        reserved = reserved_product_quantity(db, item.id) if item.kind == "PRODUCT" else 0
        data["reserved_qty"] = reserved
        data["available_qty"] = max(float(item.stock_qty) - reserved, 0)
        rows.append(data)
    return rows


@app.get("/api/stock/transactions")
def stock_transactions(
    limit: int = Query(100, ge=1, le=500),
    keyword: str = "",
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    query = (
        select(StockTransaction)
        .options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item), selectinload(StockTransaction.related_order))
    )
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        item_matches = or_(InventoryItem.sku.ilike(token), InventoryItem.name.ilike(token))
        query = query.where(
            or_(
                StockTransaction.transaction_no.ilike(token),
                StockTransaction.notes.ilike(token),
                StockTransaction.lines.any(StockTransactionItem.item.has(item_matches)),
            )
        )
    if transaction_type and transaction_type.strip():
        query = query.where(StockTransaction.transaction_type == transaction_type.strip().upper())
    if start_date:
        query = query.where(StockTransaction.occurred_at >= datetime.combine(start_date, time.min))
    if end_date:
        query = query.where(StockTransaction.occurred_at <= datetime.combine(end_date, time.max))
    txs = db.scalars(query.order_by(StockTransaction.occurred_at.desc()).limit(limit)).all()
    return [transaction_dict(tx) for tx in txs]


@app.post("/api/stock/inbound", status_code=201)
def inbound(payload: StockPayload, db: Session = Depends(get_db)):
    item = find_item(db, payload.item_id)
    if item.kind == "PRODUCT" and not float(payload.quantity).is_integer():
        raise HTTPException(422, "产品入库数量必须为正整数")
    changes: list[tuple[InventoryItem, float, float]] = []
    tx_type = "PURCHASE_IN" if item.kind == "PART" else "MANUAL_IN"
    production_run = None
    if payload.production_run_id is not None:
        production_run = db.get(ProductionRun, payload.production_run_id)
        if not production_run or production_run.product_id != item.id:
            raise HTTPException(400, "生产批次与所选产品不匹配")
        if production_run.status not in {"PLANNED", "RUNNING"}:
            raise HTTPException(409, "该生产批次已完成或取消")
        if abs(float(payload.quantity) - float(production_run.planned_quantity)) > 1e-6:
            raise HTTPException(422, "按计划完工时，入库数量必须等于批次计划数量")
    if item.kind == "PRODUCT" and payload.consume_bom:
        product = db.scalar(
            select(InventoryItem)
            .where(InventoryItem.id == item.id)
            .options(
                selectinload(InventoryItem.bom_components)
                .selectinload(ProductBomItem.part)
            )
        )
        if not product.bom_components:
            raise HTTPException(409, "产品还没有 BOM，不能按 BOM 生产入库")
        changes.extend((line.part, -line.quantity * payload.quantity, line.part.cost_price) for line in product.bom_components)
        tx_type = "ASSEMBLY_IN"
    changes.append((item, payload.quantity, payload.unit_cost or item.cost_price))
    tx = create_transaction(db, tx_type, changes, payload.notes)
    if tx_type == "ASSEMBLY_IN":
        # Newly produced stock must immediately flow to confirmed orders by delivery priority.
        rebalance_product_reservations(db, {item.id})
        if production_run:
            production_run.produced_quantity = payload.quantity
            production_run.status = "COMPLETED"
            production_run.actual_start_at = production_run.actual_start_at or datetime.now()
            production_run.actual_end_at = datetime.now()
        recalculate_production_plan(db)
    db.commit()
    tx = db.scalar(
        select(StockTransaction)
        .where(StockTransaction.id == tx.id)
        .options(
            selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item),
            selectinload(StockTransaction.related_order),
        )
    )
    return transaction_dict(tx)


@app.post("/api/stock/outbound", status_code=201)
def outbound(payload: StockPayload, db: Session = Depends(get_db)):
    item = find_item(db, payload.item_id)
    if item.kind == "PRODUCT":
        if not float(payload.quantity).is_integer():
            raise HTTPException(422, "产品出库数量必须为正整数")
        reserved = reserved_product_quantity(db, item.id)
        free_stock = max(float(item.stock_qty) - reserved, 0)
        if payload.quantity > free_stock + 1e-9:
            raise HTTPException(409, f"{item.name} 可用库存不足；当前有 {reserved:g} {item.unit} 已被客单预留")
    tx = create_transaction(db, "MANUAL_OUT", [(item, -payload.quantity, item.cost_price)], payload.notes)
    if item.kind == "PRODUCT":
        recalculate_production_plan(db)
    db.commit()
    tx = db.scalar(
        select(StockTransaction)
        .where(StockTransaction.id == tx.id)
        .options(
            selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item),
            selectinload(StockTransaction.related_order),
        )
    )
    return transaction_dict(tx)


@app.get("/api/orders")
def orders(
    status: str | None = None,
    keyword: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    query = select(SalesOrder).options(selectinload(SalesOrder.items).selectinload(SalesOrderItem.product))
    if status:
        query = query.where(SalesOrder.status == status)
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(or_(SalesOrder.order_no.ilike(token), SalesOrder.customer_name.ilike(token), SalesOrder.customer_phone.ilike(token)))
    if start_date:
        query = query.where(SalesOrder.order_date >= start_date)
    if end_date:
        query = query.where(SalesOrder.order_date <= end_date)
    rows = db.scalars(query.order_by(SalesOrder.required_date.asc(), SalesOrder.order_date.desc(), SalesOrder.id.desc())).all()
    return [order_dict(order) for order in rows]


@app.post("/api/orders", status_code=201)
def create_order(payload: OrderPayload, db: Session = Depends(get_db)):
    ids = [line.product_id for line in payload.items]
    products = {
        item.id: item
        for item in db.scalars(
            select(InventoryItem).where(
                InventoryItem.id.in_(ids),
                InventoryItem.kind == "PRODUCT",
                InventoryItem.active.is_(True),
            )
        ).all()
    }
    if len(products) != len(ids):
        raise HTTPException(400, "客单中包含无效产品")
    order = SalesOrder(
        order_no=serial("SO"), customer_name=payload.customer_name, customer_phone=payload.customer_phone,
        customer_address=payload.customer_address, order_date=payload.order_date,
        required_date=payload.required_date or payload.order_date, notes=payload.notes, status="DRAFT"
    )
    order.items = [
        SalesOrderItem(
            product_id=line.product_id,
            quantity=line.quantity,
            reference_price=products[line.product_id].sale_price,
            unit_price=line.unit_price,
            line_total=round(line.quantity * line.unit_price, 2),
        )
        for line in payload.items
    ]
    order.total_amount = round(sum(line.line_total for line in order.items), 2)
    db.add(order)
    db.commit()
    return order_dict(load_order(db, order.id))


@app.post("/api/orders/{order_id}/confirm")
def confirm_order(order_id: int, db: Session = Depends(get_db)):
    order = load_order(db, order_id)
    if order.status != "DRAFT":
        raise HTTPException(409, "只有草稿客单可以确认")
    order.status = "CONFIRMED"
    db.flush()
    rebalance_product_reservations(db, {line.product_id for line in order.items})
    plan = recalculate_production_plan(db)
    db.commit()
    refreshed = load_order(db, order.id)
    return {
        "order": order_dict(refreshed),
        "workflow": order_workflow_dict(db, refreshed),
        "plan": plan,
    }


@app.get("/api/orders/{order_id}/availability")
def order_availability(order_id: int, db: Session = Depends(get_db)):
    return order_workflow_dict(db, load_order(db, order_id))


@app.post("/api/orders/{order_id}/prepare")
def prepare_order(order_id: int, db: Session = Depends(get_db)):
    order = load_order(db, order_id)
    if order.status not in {"CONFIRMED", "WAITING_MATERIALS", "READY_TO_SHIP"}:
        raise HTTPException(409, "只有已确认且未完结的客单可以重算计划")
    plan = recalculate_production_plan(db)
    db.commit()
    refreshed = load_order(db, order_id)
    return {
        "order": order_dict(refreshed),
        "workflow": order_workflow_dict(db, refreshed),
        "plan": plan,
    }


@app.post("/api/orders/{order_id}/receive-materials")
def receive_order_materials(
    order_id: int,
    payload: OrderStockPayload,
    db: Session = Depends(get_db),
):
    order = load_order(db, order_id)
    if order.status not in {"CONFIRMED", "WAITING_MATERIALS"}:
        raise HTTPException(409, "该客单当前不需要办理零件入库")
    workflow = order_workflow_dict(db, order)
    if workflow["next_action"] == "WAIT_PRIORITY":
        raise HTTPException(409, "该客单正在等待更早交期客单，暂不采购或生产")
    if workflow["next_action"] == "CONFIGURE_BOM":
        raise HTTPException(409, "该客单产品尚未配置 BOM，请先完善产品组成")
    shortages = [row for row in workflow["material_lines"] if row["shortage_quantity"] > 1e-9]
    if not shortages:
        plan = recalculate_production_plan(db)
        db.commit()
        refreshed = load_order(db, order_id)
        return {
            "order": order_dict(refreshed),
            "workflow": order_workflow_dict(db, refreshed),
            "plan": plan,
            "material_transaction_id": None,
        }

    part_ids = [row["part_id"] for row in shortages]
    parts = {
        item.id: item
        for item in db.scalars(
            select(InventoryItem).where(InventoryItem.id.in_(part_ids), InventoryItem.kind == "PART")
        ).all()
    }
    changes = [
        (parts[row["part_id"]], row["shortage_quantity"], parts[row["part_id"]].cost_price)
        for row in shortages
    ]
    transaction = create_transaction(
        db,
        "PURCHASE_IN",
        changes,
        payload.notes or f"客单 {order.order_no} 缺口零件入库",
        order.id,
    )
    plan = recalculate_production_plan(db)
    db.commit()
    refreshed = load_order(db, order_id)
    return {
        "order": order_dict(refreshed),
        "workflow": order_workflow_dict(db, refreshed),
        "plan": plan,
        "material_transaction_id": transaction.id,
    }


@app.post("/api/orders/{order_id}/fulfill")
def fulfill_order(order_id: int, db: Session = Depends(get_db)):
    order = load_order(db, order_id)
    if order.status != "READY_TO_SHIP":
        raise HTTPException(409, "客单尚未完成库存检查和备货，不能出库")
    if any(float(line.reserved_quantity or 0) + 1e-9 < float(line.quantity) for line in order.items):
        raise HTTPException(409, "客单产品预留数量不足，请重新执行备货检查")
    product_ids = {line.product_id for line in order.items}
    tx = create_transaction(
        db,
        "SALE_OUT",
        [
            (line.product, -line.quantity, line.product.cost_price)
            for line in order.items
        ],
        f"客单 {order.order_no} 出库",
        order.id,
    )
    release_order_reservations(db, order)
    order.status = "FULFILLED"
    db.flush()
    rebalance_product_reservations(db, product_ids)
    recalculate_production_plan(db)
    db.commit()
    return {"order": order_dict(order), "transaction_id": tx.id}


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: int, db: Session = Depends(get_db)):
    order = load_order(db, order_id)
    if order.status in {"FULFILLED", "CANCELLED"}:
        raise HTTPException(409, "已完结客单不能取消")
    product_ids = {line.product_id for line in order.items}
    release_order_reservations(db, order)
    order.status = "CANCELLED"
    db.flush()
    rebalance_product_reservations(db, product_ids)
    recalculate_production_plan(db)
    db.commit()
    return order_dict(order)


@app.get("/api/backups")
def backups():
    return list_backup_archives()


@app.post("/api/backups", status_code=201)
def create_backup(db: Session = Depends(get_db)):
    return create_backup_archive(db)


@app.get("/api/backups/{filename}/download")
def download_backup(filename: str):
    try:
        path = resolve_backup_file(filename)
    except BackupError as error:
        raise HTTPException(400, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(404, "备份文件不存在") from error
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/backups/{filename}/restore")
def restore_backup(filename: str, payload: BackupRestorePayload, db: Session = Depends(get_db)):
    if payload.confirm_filename != filename:
        raise HTTPException(400, "确认文件名与待恢复备份不一致")
    try:
        path = resolve_backup_file(filename)
        return restore_backup_archive(db, path)
    except BackupError as error:
        raise HTTPException(400, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(404, "备份文件不存在") from error


FRONTEND_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"
ASSETS_DIR = FRONTEND_DIST / "assets"
if ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=ASSETS_DIR), name="assets")


@app.get("/{full_path:path}", include_in_schema=False)
def frontend(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "API endpoint not found")
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"message": "前端尚未构建，请先执行 npm --prefix frontend run build", "api_docs": "/docs"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
