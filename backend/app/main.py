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
from starlette.middleware.base import BaseHTTPMiddleware

from .backup import BackupError, create_backup_archive, list_backup_archives, resolve_backup_file, restore_backup_archive
from .database import SessionLocal, engine, get_db, run_migrations
from .models import (
    ExternalProcessingBatch,
    InventoryItem,
    OperationLog,
    OrderReturn,
    OrderShipmentAllocation,
    Payment,
    PaymentAllocation,
    ProductBomItem,
    ProductionAllocation,
    ProductionCalendarException,
    ProductionMaterialReservation,
    ProductionRun,
    ProductionSetting,
    PurchaseCommitment,
    Receivable,
    SalesOrder,
    SalesOrderItem,
    StockReservation,
    StockTransaction,
    StockTransactionItem,
    User,
)
from .schemas import (
    BackupRestorePayload,
    CalendarExceptionPayload,
    ExternalProcessingReturnPayload,
    ExternalProcessingSendPayload,
    LoginPayload,
    ManualProductionRunPayload,
    OrderCancelPayload,
    OrderPayload,
    OrderReturnPayload,
    OrderShipmentPayload,
    OrderStockPayload,
    PartPayload,
    PaymentAllocationPayload,
    PaymentPayload,
    PrintSettingsPayload,
    ProductPayload,
    ProductionRunSchedulePayload,
    ProductionRunStatusPayload,
    ProductionCompletionPayload,
    ProductionSettingsPayload,
    PurchaseCommitmentPayload,
    PurchaseCommitmentStatusPayload,
    SamplePayload,
    StockDocumentPayload,
    StockPayload,
    StockReconciliationPayload,
    UserPayload,
    UserUpdatePayload,
)
from .planning import (
    _recalculate_plan_impl,
    list_production_runs,
    production_demand_summary,
    purchase_requirement_summary,
    recalculate_production_plan,
)
from .services import (
    RESERVATION_STATUSES,
    create_transaction,
    client_ip,
    effective_line_demand,
    ensure_sku_available,
    hash_password,
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
    verify_password,
)
from .auth import (
    EMERGENCY_TOKEN_TTL_SECONDS,
    authenticated_username,
    create_access_token,
    current_role_for,
    emergency_admin_credentials,
    extract_token,
    load_user,
    matches_emergency_admin,
    require_admin,
    required_role_for,
    role_allows,
    validate_auth_config,
    verify_token,
)


StockStatus = Literal["LOW", "NORMAL"]
BomStatus = Literal["CONFIGURED", "EMPTY"]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # 生产环境缺少 JWT 密钥等致命鉴权配置时，拒绝启动。
    validate_auth_config()
    try:
        run_migrations()
        with SessionLocal() as db:
            if os.getenv("ERP_SEED_DEMO", "0").strip().lower() in {"1", "true", "yes"}:
                seed_demo(db)
            # 迁移后的旧订单、预留和自动排期也必须立即回到同一业务事实。
            recalculate_production_plan(db)
            db.commit()
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


async def enforce_rbac(request: Request, call_next):
    """统一 RBAC 门卫：所有 /api 业务路径按角色放行，公开路径直接通过。

    顺序上位于 CORS 内层、审计广播外层——被拒绝的请求不进入业务处理器，
    也不产生操作日志（避免未认证扫描刷爆审计表）。实时刷新信号 /api/events
    仅广播变更事件、不含业务数据，保持公开以兼容 EventSource 无法携带
    Authorization 头的限制。
    """
    path = request.url.path
    if not path.startswith("/api/"):
        return await call_next(request)
    required = required_role_for(path, request.method)
    if required is None:
        return await call_next(request)
    token = extract_token(request)
    if not token:
        return JSONResponse(status_code=401, content={"detail": "需要登录后操作"})
    try:
        payload = verify_token(token)
    except HTTPException as error:
        return JSONResponse(status_code=error.status_code, content={"detail": error.detail})
    # 每次请求按数据库当前状态校验：停用用户立即踢出，角色以库内当前值为准。
    with SessionLocal() as session:
        role = current_role_for(payload, session)
    if role is None:
        return JSONResponse(status_code=401, content={"detail": "登录状态无效，请重新登录"})
    if not role_allows(role, required):
        return JSONResponse(status_code=403, content={"detail": f"当前角色（{role}）无权执行该操作"})
    return await call_next(request)


app.add_middleware(BaseHTTPMiddleware, dispatch=enforce_rbac)


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

    def publish(self, *, source: str) -> None:
        # 公开端点只广播“有变化”信号，不携带 path/method 等业务信息。
        self._sequence += 1
        payload = json.dumps(
            {
                "id": self._sequence,
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
                    username=authenticated_username(request),
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
            change_events.publish(source=request.headers.get("x-erp-client-id", ""))
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
    if path == "/api/stock/reconcile":
        return "库存对账"
    if path == "/api/stock/documents":
        return "出入库开单"
    if path.startswith("/api/orders"):
        if path.endswith("/confirm"):
            return "确认客单"
        if path.endswith("/prepare"):
            return "客单备货"
        if path.endswith("/receive-materials"):
            return "客单补料"
        if path.endswith(("/ship", "/ship-all", "/fulfill")):
            return "客单出库"
        if path.endswith("/returns"):
            return "客单退货"
        if path.endswith("/cancel"):
            return "取消客单"
        return "新建客单"
    if path.startswith("/api/external-processing"):
        return "外协回厂" if path.endswith("/return") else "外协送出"
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
    if path.startswith("/api/purchase"):
        if path.endswith("/commitments"):
            return "登记采购到货"
        return "采购需求"
    if path.startswith("/api/production/plan"):
        return "重算生产计划"
    if path.startswith("/api/production/runs"):
        if path.endswith("/schedule"):
            return "调整订单排产"
        return "更新生产批次"
    if path.startswith("/api/system/production-settings"):
        return "修改生产设置"
    if path.startswith("/api/system/print-settings"):
        return "修改打印设置"
    if path.startswith("/api/finance"):
        if path.endswith("/allocate"):
            return "核销付款"
        return "登记付款"
    if path.startswith("/api/users"):
        return {"POST": "新建用户", "PUT": "编辑用户", "DELETE": "停用用户"}.get(method, "用户管理")
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
        query = query.where(InventoryItem.stock_qty < InventoryItem.min_stock)
    elif stock_status == "NORMAL":
        query = query.where(InventoryItem.stock_qty >= InventoryItem.min_stock)
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
def login(payload: LoginPayload, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(
        select(User).where(User.username == payload.username.strip(), User.active.is_(True))
    )
    if user and verify_password(payload.password, user.password_hash):
        token = create_access_token(user.id, user.username, user.role, user.display_name or user.username)
        return {"code": 0, "data": {"token": token, "username": user.username, "display_name": user.display_name or user.username, "role": user.role}, "message": "success"}
    # Break-glass 应急管理员：默认关闭，仅显式开启且凭据满足强度要求时可用，登录留独立审计记录。
    credentials = emergency_admin_credentials()
    if credentials and matches_emergency_admin(payload.username, payload.password, credentials):
        db.add(OperationLog(
            username=credentials[0][:120],
            action="应急管理员登录",
            target="/api/v1/auth/login",
            method="POST",
            path="/api/v1/auth/login",
            ip_address=client_ip(request)[:64],
            status="SUCCESS",
            detail="Break-glass 应急管理员通过环境变量凭据登录",
        ))
        db.commit()
        # 应急令牌只活 2 小时；网关会在每次请求时确认开关仍然开启。
        token = create_access_token(0, credentials[0], "ADMIN", "应急管理员", ttl_seconds=EMERGENCY_TOKEN_TTL_SECONDS)
        return {"code": 0, "data": {"token": token, "username": credentials[0], "display_name": "应急管理员", "role": "ADMIN"}, "message": "success"}
    raise HTTPException(401, "用户名或密码错误")


@app.get("/api/v1/users/me")
def current_user(request: Request, db: Session = Depends(get_db)):
    token = extract_token(request)
    if not token:
        raise HTTPException(401, "未登录")
    try:
        payload = verify_token(token)
    except HTTPException as error:
        raise HTTPException(401, "登录状态无效，请重新登录") from error
    user_id = int(payload.get("sub", "0"))
    if user_id > 0:
        user = load_user(db, user_id)
        if user:
            return {"code": 0, "data": {"username": user.username, "display_name": user.display_name or user.username, "role": user.role, "roles": [user.role], "permissions": []}, "message": "success"}
        raise HTTPException(401, "登录状态无效，请重新登录")
    if payload.get("role") == "ADMIN" and emergency_admin_credentials() is not None:
        # 应急管理员令牌（sub=0）：开关已关闭时立即失效。
        return {"code": 0, "data": {"username": payload.get("username", ""), "display_name": payload.get("display_name", ""), "role": "ADMIN", "roles": ["ADMIN"], "permissions": []}, "message": "success"}
    raise HTTPException(401, "登录状态无效，请重新登录")


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    active = InventoryItem.active.is_(True)
    regular_inventory = InventoryItem.kind.in_(["PART", "PRODUCT"])
    part_count = db.scalar(select(func.count()).select_from(InventoryItem).where(active, InventoryItem.kind == "PART")) or 0
    product_count = db.scalar(select(func.count()).select_from(InventoryItem).where(active, InventoryItem.kind == "PRODUCT")) or 0
    low_stock = db.scalar(
        select(func.count())
        .select_from(InventoryItem)
        .where(active, regular_inventory, InventoryItem.stock_qty < InventoryItem.min_stock)
    ) or 0
    pending_orders = db.scalar(
        select(func.count())
        .select_from(SalesOrder)
        .where(SalesOrder.status.in_([
            "DRAFT", "CONFIRMED", "WAITING_MATERIALS", "READY_TO_SHIP",
            "PARTIALLY_SHIPPED",
        ]))
    ) or 0
    inventory_value = db.scalar(
        select(func.sum(InventoryItem.stock_qty * InventoryItem.cost_price)).where(active, regular_inventory)
    ) or 0
    recent_txs = db.scalars(
        select(StockTransaction)
        .options(
            selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item),
            selectinload(StockTransaction.related_order),
            selectinload(StockTransaction.related_production_run),
        )
        .order_by(StockTransaction.occurred_at.desc()).limit(6)
    ).all()
    low_items = db.scalars(
        select(InventoryItem)
        .where(active, regular_inventory, InventoryItem.stock_qty < InventoryItem.min_stock)
        .order_by(InventoryItem.stock_qty)
    ).all()
    pending_order_rows = db.scalars(
        select(SalesOrder)
        .where(SalesOrder.status.in_([
            "CONFIRMED", "WAITING_MATERIALS", "READY_TO_SHIP",
            "PARTIALLY_SHIPPED",
        ]))
        .options(
            selectinload(SalesOrder.items)
            .selectinload(SalesOrderItem.product)
            .selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part)
        )
        .order_by(SalesOrder.required_date, SalesOrder.order_date, SalesOrder.id)
    ).all()
    purchase_todos = purchase_requirement_summary(db)
    production_todos = production_demand_summary(db)
    shipping_todos: list[dict] = []
    for order in pending_order_rows:
        workflow = order_workflow_dict(db, order)
        todo = {
            "order_id": order.id,
            "order_no": order.order_no,
            "customer_name": order.customer_name,
            "required_date": (order.required_date or order.order_date).isoformat(),
        }
        if workflow["ready_to_ship"] and any(
            row["remaining_quantity"] > 0 for row in workflow["product_lines"]
        ):
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
    if (
        product
        and product.requires_external_processing
        and not payload.requires_external_processing
        and (int(product.semi_finished_qty or 0) + int(product.processing_qty or 0) > 0)
    ):
        raise HTTPException(409, "该产品仍有半成品或外协在途，不能关闭外协工序")
    part_ids = [line.part_id for line in payload.components]
    if product and product.id in part_ids:
        raise HTTPException(400, "BOM 中不能包含产品自身作为零件")
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
    if not payload.requires_external_processing:
        values["external_process_name"] = ""
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
        "working_weekdays": settings.working_weekdays or "1,2,3,4,5",
        "updated_at": settings.updated_at.isoformat(),
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
    row.working_weekdays = payload.working_weekdays.strip() or "1,2,3,4,5"
    db.flush()
    recalculate_production_plan(db)
    db.commit()
    db.refresh(row)
    return production_settings_dict(row)


def print_settings_dict(settings: ProductionSetting) -> dict:
    return {
        "paper_preset": settings.print_paper_preset,
        "width_mm": settings.print_width_mm,
        "height_mm": settings.print_height_mm,
        "updated_at": settings.updated_at.isoformat(),
    }


@app.get("/api/system/print-settings")
def print_settings(db: Session = Depends(get_db)):
    row = db.get(ProductionSetting, 1)
    if row is None:
        row = ProductionSetting(id=1)
        db.add(row)
        db.commit()
        db.refresh(row)
    return print_settings_dict(row)


@app.put("/api/system/print-settings")
def update_print_settings(
    payload: PrintSettingsPayload,
    db: Session = Depends(get_db),
):
    row = db.get(ProductionSetting, 1)
    if row is None:
        row = ProductionSetting(id=1)
        db.add(row)
    row.print_paper_preset = payload.paper_preset
    row.print_width_mm = round(payload.width_mm, 1)
    row.print_height_mm = round(payload.height_mm, 1)
    db.commit()
    db.refresh(row)
    return print_settings_dict(row)


def calendar_exception_dict(row: ProductionCalendarException) -> dict:
    return {
        "id": row.id,
        "exception_date": row.exception_date.isoformat(),
        "is_working_day": row.is_working_day,
        "note": row.note,
        "created_at": row.created_at.isoformat(),
    }


@app.get("/api/system/calendar/exceptions")
def list_calendar_exceptions(db: Session = Depends(get_db)):
    rows = db.scalars(
        select(ProductionCalendarException)
        .order_by(ProductionCalendarException.exception_date)
    ).all()
    return [calendar_exception_dict(row) for row in rows]


@app.post("/api/system/calendar/exceptions", status_code=201)
def create_calendar_exception(
    payload: CalendarExceptionPayload,
    db: Session = Depends(get_db),
):
    existing = db.scalar(
        select(ProductionCalendarException)
        .where(ProductionCalendarException.exception_date == payload.exception_date)
    )
    if existing:
        raise HTTPException(409, "该日期已有日历例外设置")
    row = ProductionCalendarException(
        exception_date=payload.exception_date,
        is_working_day=payload.is_working_day,
        note=payload.note.strip(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return calendar_exception_dict(row)


@app.delete("/api/system/calendar/exceptions/{exception_id}")
def delete_calendar_exception(exception_id: int, db: Session = Depends(get_db)):
    row = db.get(ProductionCalendarException, exception_id)
    if not row:
        raise HTTPException(404, "日历例外不存在")
    db.delete(row)
    db.commit()
    return {"ok": True}


@app.get("/api/production/runs")
def production_runs(status: str | None = None, db: Session = Depends(get_db)):
    return list_production_runs(db, status)


@app.post("/api/production/plan/recalculate")
def recalculate_plan(db: Session = Depends(get_db)):
    """系统维护用；正常业务写入会自动重算。"""
    result = recalculate_production_plan(db)
    db.commit()
    return result


@app.post("/api/production/runs/manual", status_code=201)
def create_manual_production_run(
    payload: ManualProductionRunPayload,
    db: Session = Depends(get_db),
):
    """创建独立于客单缺口的补库存生产计划。"""
    product = db.get(InventoryItem, payload.product_id)
    if not product or product.kind != "PRODUCT" or not product.active:
        raise HTTPException(404, "产品不存在")
    daily_capacity = int(product.daily_capacity or 0)
    if daily_capacity <= 0:
        raise HTTPException(409, "该产品未配置单机日产能，请先在产品目录中设置")
    if not product.bom_components:
        raise HTTPException(409, "该产品未配置 BOM，不能创建生产计划")

    settings = db.get(ProductionSetting, 1)
    line_count = max(int(settings.line_count if settings else 1), 1)
    if payload.line_slot > line_count:
        raise HTTPException(400, "生产位超出系统设置的可用范围")

    today = date.today()
    planned_start = datetime.combine(payload.planned_start_date, time.min)
    if payload.planned_start_date == today:
        planned_start = datetime.now().replace(second=0, microsecond=0)
    elif payload.planned_start_date < today:
        raise HTTPException(400, "计划开始日期不能早于今天")
    duration_seconds = max(
        float(payload.planned_quantity) / daily_capacity * 86400,
        60,
    )
    planned_end = planned_start + timedelta(seconds=duration_seconds)

    line_conflict = db.scalar(
        select(ProductionRun.id).where(
            _active_schedule_condition(),
            ProductionRun.line_slot == payload.line_slot,
            ProductionRun.planned_start_at < planned_end,
            ProductionRun.planned_end_at > planned_start,
        ).limit(1)
    )
    if line_conflict:
        raise HTTPException(409, "该生产位在所选日期已有确认排期")

    mold_slot = None
    for slot in range(1, max(int(product.mold_count or 1), 1) + 1):
        conflict = db.scalar(
            select(ProductionRun.id).where(
                _active_schedule_condition(),
                ProductionRun.product_id == product.id,
                ProductionRun.mold_slot == slot,
                ProductionRun.planned_start_at < planned_end,
                ProductionRun.planned_end_at > planned_start,
            ).limit(1)
        )
        if not conflict:
            mold_slot = slot
            break
    if mold_slot is None:
        raise HTTPException(409, "该产品在所选日期没有可用模具")

    # 先刷新订单缺口，再把自主计划优先覆盖交期最近的缺口；
    # 超出订单需求的产量在完工后自然进入自由库存。
    recalculate_production_plan(db)
    run = ProductionRun(
        run_no=serial("PR"),
        product_id=product.id,
        line_slot=payload.line_slot,
        mold_slot=mold_slot,
        planned_quantity=payload.planned_quantity,
        produced_quantity=0,
        planned_start_at=planned_start,
        planned_end_at=planned_end,
        effective_daily_capacity=daily_capacity,
        schedule_locked=True,
        source_type="REPLENISHMENT",
        notes=payload.notes.strip(),
        status="PLANNED",
        workflow_version=2,
    )
    db.add(run)
    db.flush()

    remaining = payload.planned_quantity
    sequence = 1
    order_lines = db.scalars(
        select(SalesOrderItem)
        .join(SalesOrder, SalesOrder.id == SalesOrderItem.order_id)
        .where(
            SalesOrder.status.in_(RESERVATION_STATUSES),
            SalesOrderItem.product_id == product.id,
            SalesOrderItem.production_required_quantity > 0,
        )
        .order_by(
            SalesOrder.required_date,
            SalesOrder.order_date,
            SalesOrder.id,
            SalesOrderItem.id,
        )
    ).all()
    for line in order_lines:
        quantity = min(int(line.production_required_quantity or 0), remaining)
        if quantity <= 0:
            continue
        db.add(ProductionAllocation(
            production_run_id=run.id,
            order_item_id=line.id,
            quantity=quantity,
            sequence=sequence,
            estimated_completion_at=planned_end,
        ))
        remaining -= quantity
        sequence += 1
        if remaining <= 0:
            break
    db.flush()
    _recalculate_plan_impl(db, datetime.now(), skip_rebuild_auto=True)
    db.commit()
    return next(row for row in list_production_runs(db) if row["id"] == run.id)


@app.put("/api/production/runs/{run_id}/status")
def update_production_run_status(
    run_id: int,
    payload: ProductionRunStatusPayload,
    db: Session = Depends(get_db),
):
    run = db.scalar(
        select(ProductionRun)
        .where(ProductionRun.id == run_id)
        .options(
            selectinload(ProductionRun.product)
            .selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part),
            selectinload(ProductionRun.allocations),
            selectinload(ProductionRun.material_reservations),
        )
        .with_for_update()
    )
    if not run:
        raise HTTPException(404, "生产批次不存在")
    consumption_tx = None
    inbound_tx = None
    if payload.status == "RUNNING":
        if run.status != "PLANNED":
            raise HTTPException(409, "只有待生产批次可以开始生产")
        if not run.product.bom_components:
            raise HTTPException(409, "产品未配置 BOM，不能开始生产")
        reservation_map = {
            r.part_id: float(r.quantity)
            for r in run.material_reservations
            if r.status == "ACTIVE"
        }
        for component in run.product.bom_components:
            required = float(component.quantity) * int(run.planned_quantity)
            reserved = reservation_map.get(component.part_id, 0.0)
            if reserved + 1e-9 < required:
                raise HTTPException(
                    409,
                    f"物料 {component.part.sku} {component.part.name} 预留不足："
                    f"需要 {required:g}，已预留 {reserved:g}，缺口 {required - reserved:g}",
                )
        component_changes = [
            (
                component.part,
                -float(component.quantity) * int(run.planned_quantity),
                component.part.cost_price,
            )
            for component in run.product.bom_components
        ]
        consumption_tx = create_transaction(
            db,
            "PRODUCTION_OUT",
            component_changes,
            f"生产批次 {run.run_no} 开工领料，BOM 自动出库",
            related_production_run_id=run.id,
            occurred_at=datetime.now(),
        )
        run.status = "RUNNING"
        run.schedule_locked = True
        run.actual_start_at = datetime.now()
        if run.workflow_version < 2:
            run.workflow_version = 2
        for reservation in run.material_reservations:
            if reservation.status == "ACTIVE":
                reservation.status = "CONSUMED"
    elif payload.status == "CANCELLED":
        if run.status != "PLANNED":
            raise HTTPException(409, "已开工批次请使用终止生产；未开工批次才能直接取消")
        run.status = "CANCELLED"
        for reservation in run.material_reservations:
            if reservation.status == "ACTIVE":
                reservation.status = "RELEASED"
    elif payload.status == "TERMINATED":
        if run.status != "RUNNING":
            raise HTTPException(409, "只有生产中批次可以终止生产")
        if payload.qualified_quantity is None:
            raise HTTPException(400, "终止生产必须填写合格数量")
        qualified = int(payload.qualified_quantity)
        scrap = int(payload.scrap_quantity)
        if qualified < 0 or scrap < 0:
            raise HTTPException(400, "合格数量和报废数量不能为负")
        if qualified + scrap > int(run.planned_quantity):
            raise HTTPException(400, "合格数量与报废数量之和不能超过计划数量")
        unproduced = int(run.planned_quantity) - qualified - scrap
        if unproduced > 0:
            return_changes = [
                (
                    component.part,
                    float(component.quantity) * unproduced,
                    component.part.cost_price,
                )
                for component in run.product.bom_components
            ]
            create_transaction(
                db,
                "PRODUCTION_RETURN",
                return_changes,
                payload.termination_reason or f"生产批次 {run.run_no} 终止退料，未生产 {unproduced} 套",
                related_production_run_id=run.id,
                occurred_at=datetime.now(),
            )
        external_required = bool(run.product.requires_external_processing)
        if qualified > 0:
            inbound_tx = create_transaction(
                db,
                "SEMI_FINISHED_IN" if external_required else "ASSEMBLY_IN",
                [(run.product, qualified, run.product.cost_price)],
                f"生产批次 {run.run_no} 终止入库，合格 {qualified}、报废 {scrap}",
                related_production_run_id=run.id,
                occurred_at=datetime.now(),
                apply_inventory=not external_required,
            )
            if external_required:
                run.product.semi_finished_qty = int(run.product.semi_finished_qty or 0) + qualified
        run.status = "TERMINATED"
        run.produced_quantity = qualified
        run.scrap_quantity = scrap
        run.terminated_at = datetime.now()
        run.termination_reason = payload.termination_reason.strip()
        run.actual_end_at = datetime.now()
        allocatable = qualified
        for allocation in sorted(run.allocations, key=lambda row: row.sequence):
            fulfilled = min(int(allocation.quantity), allocatable)
            if fulfilled <= 0:
                db.delete(allocation)
                continue
            allocation.quantity = fulfilled
            allocation.estimated_completion_at = run.actual_end_at
            allocatable -= fulfilled
        if not external_required:
            rebalance_product_reservations(db, {run.product_id})
    recalculate_production_plan(db)
    db.commit()
    return {
        "ok": True,
        "run_id": run_id,
        "status": run.status,
        "consumption_transaction_id": consumption_tx.id if consumption_tx else None,
        "inbound_transaction_id": inbound_tx.id if inbound_tx else None,
    }


@app.get("/api/production/demands")
def production_demands(db: Session = Depends(get_db)):
    return production_demand_summary(db)


@app.get("/api/purchase/requirements")
def purchase_requirements(db: Session = Depends(get_db)):
    return purchase_requirement_summary(db)


def purchase_commitment_dict(row: PurchaseCommitment) -> dict:
    return {
        "id": row.id,
        "part_id": row.part_id,
        "part_sku": row.part.sku,
        "part_name": row.part.name,
        "unit": row.part.unit,
        "quantity": row.quantity,
        "expected_arrival_at": row.expected_arrival_at.isoformat(),
        "status": row.status,
        "supplier_text": row.supplier_text,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@app.get("/api/purchase/commitments")
def list_purchase_commitments(
    status: str | None = None,
    db: Session = Depends(get_db),
):
    query = select(PurchaseCommitment).options(selectinload(PurchaseCommitment.part))
    if status and status.strip():
        query = query.where(PurchaseCommitment.status == status.strip().upper())
    rows = db.scalars(
        query.order_by(PurchaseCommitment.expected_arrival_at, PurchaseCommitment.id)
    ).all()
    return [purchase_commitment_dict(row) for row in rows]


@app.post("/api/purchase/commitments", status_code=201)
def create_purchase_commitment(
    payload: PurchaseCommitmentPayload,
    db: Session = Depends(get_db),
):
    part = find_item(db, payload.part_id, "PART")
    commitment = PurchaseCommitment(
        part_id=part.id,
        quantity=payload.quantity,
        expected_arrival_at=datetime.combine(payload.expected_arrival_date, time.min),
        status="PLANNED",
        supplier_text=payload.supplier_text.strip(),
        notes=payload.notes.strip(),
    )
    db.add(commitment)
    db.flush()
    recalculate_production_plan(db)
    db.commit()
    db.refresh(commitment)
    commitment.part = part
    return purchase_commitment_dict(commitment)


@app.put("/api/purchase/commitments/{commitment_id}/status")
def update_purchase_commitment_status(
    commitment_id: int,
    payload: PurchaseCommitmentStatusPayload,
    db: Session = Depends(get_db),
):
    commitment = db.scalar(
        select(PurchaseCommitment)
        .where(PurchaseCommitment.id == commitment_id)
        .options(selectinload(PurchaseCommitment.part))
    )
    if not commitment:
        raise HTTPException(404, "采购到货记录不存在")
    if commitment.status == "CANCELLED":
        raise HTTPException(409, "已取消的记录不能再次修改")
    commitment.status = payload.status
    db.flush()
    recalculate_production_plan(db)
    db.commit()
    return purchase_commitment_dict(commitment)


@app.delete("/api/purchase/commitments/{commitment_id}")
def delete_purchase_commitment(commitment_id: int, db: Session = Depends(get_db)):
    commitment = db.get(PurchaseCommitment, commitment_id)
    if not commitment:
        raise HTTPException(404, "采购到货记录不存在")
    if commitment.status == "ARRIVED":
        raise HTTPException(409, "已到货的记录不能删除")
    db.delete(commitment)
    recalculate_production_plan(db)
    db.commit()
    return {"ok": True}


@app.post("/api/production/runs/{run_id}/complete", status_code=201)
def complete_production_run(
    run_id: int,
    payload: ProductionCompletionPayload,
    db: Session = Depends(get_db),
):
    query = (
        select(ProductionRun)
        .where(ProductionRun.id == run_id)
        .options(
            selectinload(ProductionRun.product)
            .selectinload(InventoryItem.bom_components)
            .selectinload(ProductBomItem.part),
            selectinload(ProductionRun.allocations),
        )
    )
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    run = db.scalar(query)
    if not run:
        raise HTTPException(404, "生产批次不存在")
    if run.workflow_version >= 2 and run.status != "RUNNING":
        raise HTTPException(409, "新批次必须先开始生产再办理完工")
    if run.status not in {"PLANNED", "RUNNING"}:
        raise HTTPException(409, "只有待完工批次可以办理生产入库")
    if not run.product.bom_components:
        raise HTTPException(409, "产品未配置 BOM，不能办理生产入库")
    qualified = int(payload.qualified_quantity)
    scrap = int(payload.scrap_quantity)
    if qualified <= 0:
        raise HTTPException(400, "合格数量必须大于 0")
    if scrap < 0:
        raise HTTPException(400, "报废数量不能为负")
    total_consumed = qualified + scrap
    occurred_at = datetime.combine(payload.completion_date, time.min)
    consumption_tx = db.scalar(
        select(StockTransaction)
        .where(
            StockTransaction.related_production_run_id == run.id,
            StockTransaction.transaction_type == "PRODUCTION_OUT",
        )
        .order_by(StockTransaction.id.desc())
    )
    if consumption_tx is None:
        component_changes = [
            (
                component.part,
                -float(component.quantity) * total_consumed,
                component.part.cost_price,
            )
            for component in run.product.bom_components
        ]
        consumption_tx = create_transaction(
            db,
            "PRODUCTION_OUT",
            component_changes,
            payload.notes or f"生产批次 {run.run_no} 历史开工领料补记",
            related_production_run_id=run.id,
            occurred_at=run.actual_start_at or occurred_at,
        )
    elif total_consumed != int(run.planned_quantity):
        variance = total_consumed - int(run.planned_quantity)
        create_transaction(
            db,
            "PRODUCTION_OUT" if variance > 0 else "PRODUCTION_RETURN",
            [
                (
                    component.part,
                    -float(component.quantity) * variance,
                    component.part.cost_price,
                )
                for component in run.product.bom_components
            ],
            payload.notes or (
                f"生产批次 {run.run_no} 超产补领"
                if variance > 0
                else f"生产批次 {run.run_no} 少产退料"
            ),
            related_production_run_id=run.id,
            occurred_at=occurred_at,
        )
    external_required = bool(run.product.requires_external_processing)
    bom_unit_cost = (
        sum(float(component.quantity) * float(component.part.cost_price) for component in run.product.bom_components)
        * total_consumed / qualified
    ) if qualified > 0 else float(run.product.cost_price)
    inbound_tx = create_transaction(
        db,
        "SEMI_FINISHED_IN" if external_required else "ASSEMBLY_IN",
        [(run.product, qualified, bom_unit_cost)],
        payload.notes or (
            f"生产批次 {run.run_no} 半成品入库，待{run.product.external_process_name}"
            if external_required
            else f"生产批次 {run.run_no} 完工入库"
        ),
        related_production_run_id=run.id,
        occurred_at=occurred_at,
        apply_inventory=not external_required,
    )
    if external_required:
        run.product.semi_finished_qty = int(run.product.semi_finished_qty or 0) + qualified
    run.produced_quantity = qualified
    run.scrap_quantity = scrap
    run.status = "COMPLETED"
    run.actual_end_at = datetime.combine(payload.completion_date, time.min)
    allocatable = qualified
    for allocation in sorted(run.allocations, key=lambda row: row.sequence):
        fulfilled = min(int(allocation.quantity), allocatable)
        if fulfilled <= 0:
            db.delete(allocation)
            continue
        allocation.quantity = fulfilled
        allocation.estimated_completion_at = run.actual_end_at
        allocatable -= fulfilled
    if not external_required:
        rebalance_product_reservations(db, {run.product_id})
    plan = recalculate_production_plan(db)
    db.commit()
    return {
        "transaction_id": inbound_tx.id,
        "consumption_transaction_id": consumption_tx.id,
        "run_id": run.id,
        "planned_quantity": run.planned_quantity,
        "qualified_quantity": qualified,
        "scrap_quantity": scrap,
        "excess_quantity": max(total_consumed - int(run.planned_quantity), 0),
        "inventory_bucket": "SEMI_FINISHED" if external_required else "FINISHED",
        "plan": plan,
    }


def external_batch_dict(batch: ExternalProcessingBatch) -> dict:
    return {
        "id": batch.id,
        "batch_no": batch.batch_no,
        "product_id": batch.product_id,
        "product_sku": batch.product.sku,
        "product_name": batch.product.name,
        "unit": batch.product.unit,
        "process_name": batch.process_name_snapshot,
        "supplier": batch.supplier,
        "quantity": batch.quantity,
        "returned_quantity": batch.returned_quantity,
        "remaining_quantity": max(batch.quantity - batch.returned_quantity, 0),
        "status": batch.status,
        "notes": batch.notes,
        "sent_at": batch.sent_at.isoformat(),
        "expected_return_at": batch.expected_return_at.isoformat() if batch.expected_return_at else None,
        "returned_at": batch.returned_at.isoformat() if batch.returned_at else None,
    }


@app.get("/api/external-processing")
def external_processing(db: Session = Depends(get_db)):
    products = db.scalars(
        select(InventoryItem)
        .where(
            InventoryItem.kind == "PRODUCT",
            InventoryItem.active.is_(True),
            InventoryItem.requires_external_processing.is_(True),
        )
        .order_by(InventoryItem.sku)
    ).all()
    batches = db.scalars(
        select(ExternalProcessingBatch)
        .options(selectinload(ExternalProcessingBatch.product))
        .order_by(ExternalProcessingBatch.sent_at.desc(), ExternalProcessingBatch.id.desc())
    ).all()
    return {
        "products": [item_dict(product) for product in products],
        "batches": [external_batch_dict(batch) for batch in batches],
    }


@app.post("/api/external-processing/send", status_code=201)
def send_external_processing(
    payload: ExternalProcessingSendPayload,
    db: Session = Depends(get_db),
):
    product = db.get(InventoryItem, payload.product_id)
    if not product or product.kind != "PRODUCT" or not product.active:
        raise HTTPException(404, "产品不存在")
    if not product.requires_external_processing or not product.external_process_name:
        raise HTTPException(409, "该产品未配置外协工序")
    occurred_at = datetime.combine(payload.occurred_date, time.min)
    outbound_tx = create_transaction(
        db,
        "PROCESS_OUT",
        [(product, -payload.quantity, product.cost_price)],
        payload.notes or f"{product.external_process_name}外协送出",
        occurred_at=occurred_at,
        counterparty_name=payload.supplier,
        apply_inventory=False,
    )
    if int(product.semi_finished_qty or 0) < payload.quantity:
        raise HTTPException(
            409,
            f"{product.name} 半成品不足，当前 {int(product.semi_finished_qty or 0)} {product.unit}",
        )
    product.semi_finished_qty = int(product.semi_finished_qty or 0) - payload.quantity
    product.processing_qty = int(product.processing_qty or 0) + payload.quantity
    lead_days = int(payload.lead_days or 0)
    if lead_days <= 0:
        lead_days = int(product.default_external_lead_days or 0)
    expected_return_at = occurred_at + timedelta(days=lead_days) if lead_days > 0 else None
    batch = ExternalProcessingBatch(
        batch_no=serial("EP"),
        product_id=product.id,
        process_name_snapshot=product.external_process_name,
        supplier=payload.supplier.strip(),
        quantity=payload.quantity,
        outbound_transaction_id=outbound_tx.id,
        notes=payload.notes.strip(),
        sent_at=occurred_at,
        expected_return_at=expected_return_at,
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    batch.product = product
    return external_batch_dict(batch)


@app.post("/api/external-processing/{batch_id}/return", status_code=201)
def return_external_processing(
    batch_id: int,
    payload: ExternalProcessingReturnPayload,
    db: Session = Depends(get_db),
):
    query = (
        select(ExternalProcessingBatch)
        .where(ExternalProcessingBatch.id == batch_id)
        .options(selectinload(ExternalProcessingBatch.product))
    )
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    batch = db.scalar(query)
    if not batch:
        raise HTTPException(404, "外协批次不存在")
    remaining = max(batch.quantity - batch.returned_quantity, 0)
    if payload.quantity > remaining:
        raise HTTPException(409, f"本批次最多还能回厂 {remaining} {batch.product.unit}")
    occurred_at = datetime.combine(payload.occurred_date, time.min)
    inbound_tx = create_transaction(
        db,
        "PROCESS_RETURN_IN",
        [(batch.product, payload.quantity, batch.product.cost_price)],
        payload.notes or f"{batch.process_name_snapshot}外协回厂",
        occurred_at=occurred_at,
        counterparty_name=batch.supplier,
    )
    if int(batch.product.processing_qty or 0) < payload.quantity:
        raise HTTPException(409, "产品外协在途数量异常，请刷新后重试")
    batch.product.processing_qty = int(batch.product.processing_qty or 0) - payload.quantity
    batch.returned_quantity += payload.quantity
    batch.status = "RETURNED" if batch.returned_quantity >= batch.quantity else "PARTIALLY_RETURNED"
    batch.returned_at = occurred_at
    rebalance_product_reservations(db, {batch.product_id})
    plan = recalculate_production_plan(db)
    db.commit()
    return {
        "batch": external_batch_dict(batch),
        "transaction_id": inbound_tx.id,
        "plan": plan,
    }


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
    if run.source_type == "REPLENISHMENT":
        raise HTTPException(409, "自主补库存计划不存在自动排产来源，不能恢复为系统建议")
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
        query = query.where(InventoryItem.stock_qty < InventoryItem.min_stock)
    elif stock_status == "NORMAL":
        query = query.where(InventoryItem.stock_qty >= InventoryItem.min_stock)
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(
            or_(InventoryItem.sku.ilike(token), InventoryItem.name.ilike(token), InventoryItem.spec.ilike(token))
        )
    items = db.scalars(query.order_by(InventoryItem.kind, InventoryItem.sku)).all()
    product_demands = {
        row["product_id"]: row
        for row in production_demand_summary(db)
    }
    part_requirements = {
        row["part_id"]: row
        for row in purchase_requirement_summary(db, shortages_only=False)
    }
    rows = []
    for item in items:
        data = item_dict(item)
        reserved = reserved_product_quantity(db, item.id) if item.kind == "PRODUCT" else 0
        requirement = (
            product_demands.get(item.id, {})
            if item.kind == "PRODUCT"
            else part_requirements.get(item.id, {})
        )
        required_qty = (
            requirement.get("total_production_required", 0)
            if item.kind == "PRODUCT"
            else requirement.get("total_required", 0)
        )
        shortage_qty = (
            required_qty
            if item.kind == "PRODUCT"
            else requirement.get("shortage_quantity", 0)
        )
        data["reserved_qty"] = reserved
        data["available_qty"] = max(float(item.stock_qty) - reserved, 0)
        data["order_required_qty"] = required_qty
        data["shortage_qty"] = shortage_qty
        data["gap_qty"] = -shortage_qty if shortage_qty > 0 else 0
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


def _document_rows(
    db: Session,
    direction: Literal["INBOUND", "OUTBOUND"],
    scope: Literal["PART", "PRODUCT"] | None = None,
    keyword: str = "",
    item_id: int | None = None,
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
):
    types = (
        (
            "PURCHASE_IN", "ASSEMBLY_IN", "SEMI_FINISHED_IN",
            "PROCESS_RETURN_IN", "SALE_RETURN_IN", "MANUAL_IN",
            "GENERAL_IN", "OPENING",
        )
        if direction == "INBOUND"
        else (
            "SALE_OUT", "PROCESS_OUT", "MANUAL_OUT", "GENERAL_OUT",
            "PRODUCTION_OUT", "ASSEMBLY_IN",
        )
    )
    direction_filter = (
        StockTransactionItem.quantity_change > 0
        if direction == "INBOUND"
        else StockTransactionItem.quantity_change < 0
    )
    line_filter = direction_filter
    if scope:
        line_filter = and_(
            line_filter,
            StockTransactionItem.item.has(InventoryItem.kind == scope),
        )
    if item_id is not None:
        line_filter = and_(line_filter, StockTransactionItem.item_id == item_id)
    query = (
        select(StockTransaction)
        .where(
            StockTransaction.transaction_type.in_(types),
            StockTransaction.lines.any(line_filter),
        )
        .options(
            selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item),
            selectinload(StockTransaction.related_order),
            selectinload(StockTransaction.related_production_run),
            selectinload(StockTransaction.shipment_allocations).selectinload(OrderShipmentAllocation.order_item),
        )
    )
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        item_keyword = or_(
            StockTransactionItem.sku_snapshot.ilike(token),
            StockTransactionItem.name_snapshot.ilike(token),
            StockTransactionItem.spec_snapshot.ilike(token),
            StockTransactionItem.item.has(or_(
                InventoryItem.sku.ilike(token),
                InventoryItem.name.ilike(token),
                InventoryItem.spec.ilike(token),
            )),
        )
        query = query.where(or_(
            StockTransaction.transaction_no.ilike(token),
            StockTransaction.order_no_snapshot.ilike(token),
            StockTransaction.counterparty_name_snapshot.ilike(token),
            StockTransaction.notes.ilike(token),
            StockTransaction.lines.any(item_keyword),
        ))
    if transaction_type and transaction_type.strip():
        query = query.where(
            StockTransaction.transaction_type == transaction_type.strip().upper()
        )
    if start_date:
        query = query.where(
            StockTransaction.occurred_at >= datetime.combine(start_date, time.min)
        )
    if end_date:
        query = query.where(
            StockTransaction.occurred_at <= datetime.combine(end_date, time.max)
        )
    transactions = db.scalars(
        query.order_by(StockTransaction.occurred_at.desc()).limit(500)
    ).all()
    result = []
    for transaction in transactions:
        data = transaction_dict(transaction)
        data["lines"] = [
            line
            for line in data["lines"]
            if (line["quantity_change"] > 0) == (direction == "INBOUND")
            and (scope is None or line["kind"] == scope)
        ]
        if data["lines"]:
            result.append(data)
    return result


@app.get("/api/documents/inbound")
def inbound_documents(
    scope: Literal["PART", "PRODUCT"] | None = None,
    keyword: str = "",
    item_id: int | None = None,
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    return _document_rows(
        db,
        "INBOUND",
        scope,
        keyword,
        item_id,
        transaction_type,
        start_date,
        end_date,
    )


@app.get("/api/documents/outbound")
def outbound_documents(
    scope: Literal["PART", "PRODUCT"] | None = None,
    keyword: str = "",
    item_id: int | None = None,
    transaction_type: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    return _document_rows(
        db,
        "OUTBOUND",
        scope,
        keyword,
        item_id,
        transaction_type,
        start_date,
        end_date,
    )


@app.post("/api/stock/inbound", status_code=201)
def inbound(payload: StockPayload, db: Session = Depends(get_db)):
    item = find_item(db, payload.item_id)
    if item.kind == "PRODUCT" and not float(payload.quantity).is_integer():
        raise HTTPException(422, "产品入库数量必须为正整数")
    changes: list[tuple[InventoryItem, float, float]] = []
    tx_type = "PURCHASE_IN" if item.kind == "PART" else "MANUAL_IN"
    if payload.production_run_id is not None:
        raise HTTPException(410, "生产批次请从“生产入库”页面办理完工入库")
    if item.kind == "PRODUCT" and payload.consume_bom:
        raise HTTPException(410, 'BOM 生产入库请从"生产入库"页面办理完工入库')
    changes.append((item, payload.quantity, payload.unit_cost or item.cost_price))
    tx = create_transaction(db, tx_type, changes, payload.notes)
    if item.kind == "PRODUCT":
        # 新增成品必须立即按交期流向活动订单。
        rebalance_product_reservations(db, {item.id})
    # 零件到货、普通成品入库都会改变待购买、可承诺库存或 ETA。
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


@app.post("/api/stock/documents", status_code=201)
def create_stock_document(
    payload: StockDocumentPayload,
    db: Session = Depends(get_db),
):
    item_ids = [line.item_id for line in payload.items]
    items = {
        item.id: item
        for item in db.scalars(
            select(InventoryItem).where(
                InventoryItem.id.in_(item_ids),
                InventoryItem.active.is_(True),
                InventoryItem.kind.in_(("PART", "PRODUCT")),
            )
        ).all()
    }
    if len(items) != len(item_ids):
        raise HTTPException(404, "单据中有物料不存在或已停用")

    outbound = payload.direction == "OUTBOUND"
    changes: list[tuple[InventoryItem, float, float]] = []
    price_snapshots: dict[int, tuple[float, float]] = {}
    affected_products: set[int] = set()
    for line in payload.items:
        item = items[line.item_id]
        quantity = float(line.quantity)
        if item.kind == "PRODUCT" and not quantity.is_integer():
            raise HTTPException(422, f"{item.name} 的产品数量必须为正整数")
        if outbound and item.kind == "PRODUCT":
            reserved = reserved_product_quantity(db, item.id)
            free_stock = max(float(item.stock_qty) - reserved, 0)
            if quantity > free_stock + 1e-9:
                raise HTTPException(
                    409,
                    f"{item.name} 可用库存不足；当前有 {reserved:g} {item.unit} 已被客单预留",
                )
        signed_quantity = -quantity if outbound else quantity
        unit_cost = item.cost_price if outbound else (line.unit_price or item.cost_price)
        changes.append((item, signed_quantity, unit_cost))
        price_snapshots[item.id] = (
            float(line.unit_price),
            round(float(line.unit_price) * quantity, 2),
        )
        if item.kind == "PRODUCT":
            affected_products.add(item.id)

    tx = create_transaction(
        db,
        "GENERAL_OUT" if outbound else "GENERAL_IN",
        changes,
        payload.notes,
        occurred_at=datetime.combine(payload.occurred_date, time.min),
        operator=payload.operator,
        price_snapshots=price_snapshots,
        counterparty_name=payload.counterparty_name,
        counterparty_phone=payload.counterparty_phone,
        counterparty_address=payload.counterparty_address,
    )
    if affected_products:
        rebalance_product_reservations(db, affected_products)
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


@app.get("/api/orders/{order_id}")
def get_order(order_id: int, db: Session = Depends(get_db)):
    return order_dict(load_order(db, order_id))


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


@app.put("/api/orders/{order_id}")
def update_order(order_id: int, payload: OrderPayload, db: Session = Depends(get_db)):
    order = load_order(db, order_id)
    if any(int(line.shipped_quantity or 0) > 0 for line in order.items):
        raise HTTPException(409, "订单已经发生出库，客户、产品、数量和价格已冻结")
    if order.status != "DRAFT":
        raise HTTPException(409, "只有草稿订单可以编辑")
    product_ids = [line.product_id for line in payload.items]
    products = {
        item.id: item
        for item in db.scalars(select(InventoryItem).where(
            InventoryItem.id.in_(product_ids),
            InventoryItem.kind == "PRODUCT",
            InventoryItem.active.is_(True),
        )).all()
    }
    if len(products) != len(product_ids):
        raise HTTPException(400, "客单中包含无效产品")
    order.customer_name = payload.customer_name
    order.customer_phone = payload.customer_phone
    order.customer_address = payload.customer_address
    order.order_date = payload.order_date
    order.required_date = payload.required_date or payload.order_date
    order.notes = payload.notes
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


def order_return_dict(row: OrderReturn) -> dict:
    return {
        "id": row.id,
        "return_no": row.return_no,
        "order_id": row.order_id,
        "order_item_id": row.order_item_id,
        "product_id": row.product_id,
        "product_sku": row.product.sku,
        "product_name": row.product.name,
        "unit": row.product.unit,
        "quantity": row.quantity,
        "restocked": row.restocked,
        "resolution": row.resolution or "REFUND",
        "transaction_id": row.transaction_id,
        "notes": row.notes,
        "occurred_at": row.occurred_at.isoformat(),
    }


@app.get("/api/orders/{order_id}/returns")
def order_returns(order_id: int, db: Session = Depends(get_db)):
    if not db.get(SalesOrder, order_id):
        raise HTTPException(404, "客单不存在")
    rows = db.scalars(
        select(OrderReturn)
        .where(OrderReturn.order_id == order_id)
        .options(selectinload(OrderReturn.product))
        .order_by(OrderReturn.occurred_at.desc(), OrderReturn.id.desc())
    ).all()
    return [order_return_dict(row) for row in rows]


@app.post("/api/orders/{order_id}/returns", status_code=201)
def create_order_return(
    order_id: int,
    payload: OrderReturnPayload,
    db: Session = Depends(get_db),
):
    order = load_order(db, order_id)
    line_by_id = {line.id: line for line in order.items}
    if any(line.order_item_id not in line_by_id for line in payload.items):
        raise HTTPException(400, "退货明细不属于该客单")
    return_no = serial("RT")
    occurred_at = datetime.combine(payload.occurred_date, time.min)
    restock_changes = []
    for requested in payload.items:
        line = line_by_id[requested.order_item_id]
        returnable = max(
            int(line.shipped_quantity or 0)
            + int(line.replacement_shipped_quantity or 0)
            - int(line.returned_quantity or 0),
            0,
        )
        if requested.quantity > returnable:
            raise HTTPException(
                409,
                f"{line.product.name} 最多可退 {returnable} {line.product.unit}",
            )
        # restock 语义对所有 resolution 一致：勾选回库就生成退货入库（退款或换货皆可）。
        if requested.restock:
            restock_changes.append((line.product, requested.quantity, line.product.cost_price))
    transaction = None
    if restock_changes:
        transaction = create_transaction(
            db,
            "SALE_RETURN_IN",
            restock_changes,
            payload.notes or f"客单 {order.order_no} 退货入库（{'退款' if payload.resolution == 'REFUND' else '换货'}）",
            related_order_id=order.id,
            occurred_at=occurred_at,
        )
    created = []
    affected_products: set[int] = set()
    for requested in payload.items:
        line = line_by_id[requested.order_item_id]
        line.returned_quantity = int(line.returned_quantity or 0) + requested.quantity
        if payload.resolution == "REPLACE":
            line.replacement_pending_quantity = int(line.replacement_pending_quantity or 0) + requested.quantity
        row = OrderReturn(
            return_no=return_no,
            order_id=order.id,
            order_item_id=line.id,
            product_id=line.product_id,
            quantity=requested.quantity,
            restocked=requested.restock,
            resolution=payload.resolution,
            transaction_id=transaction.id if requested.restock and transaction else None,
            notes=payload.notes.strip(),
            occurred_at=occurred_at,
        )
        db.add(row)
        created.append(row)
        # 换货（REPLACE）即使不回库也改变了有效需求与订单状态，必须重算预留；
        # 否则订单停留在 FULFILLED，换货补发会被出库状态检查拒绝。
        if requested.restock or payload.resolution == "REPLACE":
            affected_products.add(line.product_id)
    if payload.resolution == "REPLACE" and order.status == "FULFILLED":
        # 已完结订单出现待补换货 → 重开为部分出库，让预留/排产重新接管；
        # FULFILLED 不在预留状态集合里，不重开的话补发会被出库状态检查永久拒绝。
        order.status = "PARTIALLY_SHIPPED"
    if affected_products:
        rebalance_product_reservations(db, affected_products)
        recalculate_production_plan(db)
    db.commit()
    for row in created:
        row.product = line_by_id[row.order_item_id].product
    return {
        "return_no": return_no,
        "resolution": payload.resolution,
        "transaction_id": transaction.id if transaction else None,
        "items": [order_return_dict(row) for row in created],
        "order": order_dict(load_order(db, order.id)),
    }


@app.post("/api/orders/{order_id}/prepare", deprecated=True)
def prepare_order(order_id: int, db: Session = Depends(get_db)):
    raise HTTPException(410, "订单级备货已停用；系统会自动聚合待购买和待生产需求")


@app.post("/api/orders/{order_id}/receive-materials", deprecated=True)
def receive_order_materials(
    order_id: int,
    payload: OrderStockPayload,
    db: Session = Depends(get_db),
):
    raise HTTPException(410, "订单级补料已停用；请按待购买汇总在出入库页面办理采购入库")


def _ship_order(
    db: Session,
    order_id: int,
    requested: dict[int, int] | None,
    notes: str = "",
    price_overrides: dict[int, float] | None = None,
    occurred_at: datetime | None = None,
    operator: str | None = None,
    counterparty_name: str | None = None,
    counterparty_phone: str | None = None,
    counterparty_address: str | None = None,
) -> dict:
    query = (
        select(SalesOrder)
        .where(SalesOrder.id == order_id)
        .options(selectinload(SalesOrder.items).selectinload(SalesOrderItem.product))
    )
    if db.bind and db.bind.dialect.name != "sqlite":
        query = query.with_for_update()
    order = db.scalar(query)
    if not order:
        raise HTTPException(404, "客单不存在")
    if order.status not in {
        "CONFIRMED", "WAITING_MATERIALS", "READY_TO_SHIP", "PARTIALLY_SHIPPED",
    }:
        raise HTTPException(409, "该客单当前不能出库")
    lines = sorted(order.items, key=lambda line: line.id)
    line_by_id = {line.id: line for line in lines}
    if requested is None:
        requested = {
            line.id: effective_line_demand(line)
            for line in lines
        }
    if not requested or any(line_id not in line_by_id for line_id in requested):
        raise HTTPException(400, "出库明细不属于该客单")
    reservations = {
        row.order_item_id: row
        for row in db.scalars(
            select(StockReservation)
            .where(StockReservation.order_item_id.in_(sorted(requested)))
            .order_by(StockReservation.order_item_id)
            .with_for_update()
        ).all()
    }
    changes = []
    price_snapshots: dict[int, tuple[float, float]] = {}
    # 履约计划：每行拆成 (原单数量, 换货数量)，出库流水与后续记账都用它。
    fulfillment_plan: list[tuple[SalesOrderItem, int, int, float]] = []
    for line_id, quantity in requested.items():
        line = line_by_id[line_id]
        original_remaining = max(int(line.quantity) - int(line.shipped_quantity or 0), 0)
        replacement_remaining = int(line.replacement_pending_quantity or 0)
        effective_remaining = original_remaining + replacement_remaining
        reserved = int(reservations.get(line_id).quantity if reservations.get(line_id) else 0)
        if quantity <= 0:
            raise HTTPException(422, "出库数量必须为正整数")
        if quantity > effective_remaining:
            raise HTTPException(
                409,
                f"{line.product.name} 本次出库超过剩余数量 {effective_remaining}"
                + (f"（含待补换货 {replacement_remaining}）" if replacement_remaining else ""),
            )
        if quantity > reserved:
            raise HTTPException(409, f"{line.product.name} 当前仅为本单预留 {reserved} {line.product.unit}")
        # 拆分规则：先满足原单剩余，其余数量记为换货补发。
        original_quantity = min(quantity, original_remaining)
        replacement_quantity = quantity - original_quantity
        changes.append((line.product, -quantity, line.product.cost_price))
        unit_price = float((price_overrides or {}).get(line_id, line.unit_price))
        # 单据金额快照只按原单履约计价：换货补发不产生新的销售金额。
        price_snapshots[line.product_id] = (
            unit_price,
            round(unit_price * original_quantity, 2),
        )
        fulfillment_plan.append((line, original_quantity, replacement_quantity, unit_price))
    tx = create_transaction(
        db,
        "SALE_OUT",
        changes,
        notes or f"客单 {order.order_no} 出库",
        related_order_id=order.id,
        occurred_at=occurred_at,
        operator=operator,
        price_snapshots=price_snapshots,
        counterparty_name=counterparty_name,
        counterparty_phone=counterparty_phone,
        counterparty_address=counterparty_address,
    )
    affected_products = set()
    # 应收只按原单履约计价：换货补发是对已收货款的补货，不再产生新的应收。
    original_total = 0.0
    for line, original_quantity, replacement_quantity, unit_price in fulfillment_plan:
        if original_quantity > 0:
            line.shipped_quantity = int(line.shipped_quantity or 0) + original_quantity
            original_total += unit_price * original_quantity
            db.add(OrderShipmentAllocation(
                order_item_id=line.id,
                stock_transaction_id=tx.id,
                fulfillment_type="ORIGINAL",
                quantity=original_quantity,
                unit_price_snapshot=round(unit_price, 2),
            ))
        if replacement_quantity > 0:
            line.replacement_pending_quantity = max(
                int(line.replacement_pending_quantity or 0) - replacement_quantity, 0
            )
            line.replacement_shipped_quantity = int(line.replacement_shipped_quantity or 0) + replacement_quantity
            db.add(OrderShipmentAllocation(
                order_item_id=line.id,
                stock_transaction_id=tx.id,
                fulfillment_type="REPLACEMENT",
                quantity=replacement_quantity,
                unit_price_snapshot=round(unit_price, 2),
            ))
        affected_products.add(line.product_id)
    db.flush()
    if original_total > 0:
        db.add(Receivable(
            receivable_no=serial("AR"),
            order_id=order.id,
            related_stock_transaction_id=tx.id,
            customer_name=order.customer_name,
            amount=round(original_total, 2),
            status="OPEN",
            notes=f"客单 {order.order_no} 出库应收",
        ))
    rebalance_product_reservations(db, affected_products)
    recalculate_production_plan(db)
    db.commit()
    return {
        "order": order_dict(load_order(db, order.id)),
        "transaction_id": tx.id,
        "transaction_no": tx.transaction_no,
    }


@app.post("/api/orders/{order_id}/ship", status_code=201)
def ship_order_lines(
    order_id: int,
    payload: OrderShipmentPayload,
    db: Session = Depends(get_db),
):
    return _ship_order(
        db,
        order_id,
        {line.order_item_id: line.quantity for line in payload.items},
        payload.notes,
        {line.order_item_id: line.unit_price for line in payload.items if line.unit_price is not None},
        datetime.combine(payload.occurred_date, time.min),
        payload.operator,
        payload.counterparty_name or None,
        payload.counterparty_phone or None,
        payload.counterparty_address or None,
    )


@app.post("/api/orders/{order_id}/ship-all", status_code=201)
def ship_order_all(order_id: int, db: Session = Depends(get_db)):
    return _ship_order(db, order_id, None)


@app.post("/api/orders/{order_id}/fulfill", deprecated=True)
def fulfill_order(order_id: int, db: Session = Depends(get_db)):
    """旧客户端兼容别名；新前端使用 ship-all。"""
    return _ship_order(db, order_id, None)


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(
    order_id: int,
    payload: OrderCancelPayload | None = None,
    db: Session = Depends(get_db),
):
    order = load_order(db, order_id)
    if order.status in {"FULFILLED", "CANCELLED"}:
        raise HTTPException(409, "已完结客单不能取消")
    if any(int(line.shipped_quantity or 0) > 0 for line in order.items):
        raise HTTPException(409, "订单已经发生出库，不能取消；请继续处理剩余数量")
    line_ids = [line.id for line in order.items]
    line_by_id = {line.id: line for line in order.items}
    allocations = db.scalars(
        select(ProductionAllocation)
        .where(ProductionAllocation.order_item_id.in_(line_ids))
        .options(selectinload(ProductionAllocation.production_run))
    ).all() if line_ids else []
    locked_planned_runs = []
    running_runs = []
    for allocation in allocations:
        run = allocation.production_run
        if run.status == "PLANNED" and run.schedule_locked:
            if run not in locked_planned_runs:
                locked_planned_runs.append(run)
        elif run.status == "RUNNING":
            if run not in running_runs:
                running_runs.append(run)
    if (locked_planned_runs or running_runs) and (payload is None or payload.disposition is None):
        raise HTTPException(409, {
            "message": "订单取消后，已有人工排定或生产中计划仍存在",
            "locked_planned_runs": [
                {"id": r.id, "run_no": r.run_no, "planned_quantity": r.planned_quantity}
                for r in locked_planned_runs
            ],
            "running_runs": [
                {"id": r.id, "run_no": r.run_no, "planned_quantity": r.planned_quantity}
                for r in running_runs
            ],
            "options": [
                {"value": "cancel_runs", "label": "同时取消未开工生产计划"},
                {"value": "convert_to_replenishment", "label": "保留计划并转为自主补库存"},
                {"value": "keep_runs", "label": "保留计划，仅解除订单关联"},
            ],
        })
    disposition = payload.disposition if payload else None
    runs_to_shrink = {}
    for allocation in allocations:
        run = allocation.production_run
        if run.status == "RUNNING":
            db.delete(allocation)
        elif run.status == "PLANNED" and run.schedule_locked:
            if disposition == "cancel_runs":
                remaining_allocations = db.scalars(
                    select(ProductionAllocation).where(
                        ProductionAllocation.production_run_id == run.id,
                        ProductionAllocation.id != allocation.id,
                    )
                ).all()
                if not remaining_allocations:
                    run.status = "CANCELLED"
                    for reservation in run.material_reservations:
                        if reservation.status == "ACTIVE":
                            reservation.status = "RELEASED"
                else:
                    runs_to_shrink[run.id] = run
                db.delete(allocation)
            elif disposition == "convert_to_replenishment":
                run.source_type = "REPLENISHMENT"
                db.delete(allocation)
            else:
                db.delete(allocation)
    db.flush()
    for run in runs_to_shrink.values():
        remaining_qty = sum(int(a.quantity) for a in run.allocations)
        if remaining_qty > 0 and remaining_qty < int(run.planned_quantity):
            run.planned_quantity = remaining_qty
            duration_seconds = max(
                float(remaining_qty) / max(float(run.effective_daily_capacity), 1e-9) * 86400,
                60,
            )
            run.planned_end_at = run.planned_start_at + timedelta(seconds=duration_seconds)
    product_ids = {line.product_id for line in order.items}
    release_order_reservations(db, order)
    order.status = "CANCELLED"
    db.flush()
    rebalance_product_reservations(db, product_ids)
    recalculate_production_plan(db)
    db.commit()
    return order_dict(order)


def _sale_out_reversal_deltas(db: Session, original: StockTransaction) -> dict[int, dict[str, int]]:
    """冲销一张 SALE_OUT 需要恢复的订单行数量：{order_item_id: {original: x, replacement: y}}。

    优先按履约分配精确计算；没有分配记录的历史流水退回旧行为（按产品反查，全部记 original）。
    """
    deltas: dict[int, dict[str, int]] = {}
    allocations = db.scalars(
        select(OrderShipmentAllocation)
        .where(OrderShipmentAllocation.stock_transaction_id == original.id)
    ).all()
    if allocations:
        for allocation in allocations:
            entry = deltas.setdefault(allocation.order_item_id, {"original": 0, "replacement": 0})
            key = "replacement" if allocation.fulfillment_type == "REPLACEMENT" else "original"
            entry[key] += int(allocation.quantity)
        return deltas
    if not original.related_order_id:
        return deltas
    for line in original.lines:
        if line.quantity_change >= 0:
            continue
        order_item = db.scalar(
            select(SalesOrderItem).where(
                SalesOrderItem.product_id == line.item_id,
                SalesOrderItem.order_id == original.related_order_id,
            )
        )
        if order_item:
            entry = deltas.setdefault(order_item.id, {"original": 0, "replacement": 0})
            entry["original"] += -int(line.quantity_change)
    return deltas


@app.post("/api/stock/transactions/{transaction_id}/reverse", status_code=201)
def reverse_stock_transaction(transaction_id: int, db: Session = Depends(get_db)):
    original = db.scalar(
        select(StockTransaction)
        .where(StockTransaction.id == transaction_id)
        .options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item))
    )
    if not original:
        raise HTTPException(404, "库存流水不存在")
    if original.status == "REVERSED":
        raise HTTPException(409, "该流水已被冲销，不能再次冲销")
    if original.transaction_type == "REVERSAL":
        raise HTTPException(409, "冲销单不能再次冲销")
    REVERSABLE_TYPES = {"GENERAL_IN", "GENERAL_OUT", "MANUAL_IN", "MANUAL_OUT", "PURCHASE_IN", "SALE_OUT"}
    if original.transaction_type not in REVERSABLE_TYPES:
        raise HTTPException(
            409,
            f"{original.transaction_type} 流水不支持通用冲销；生产/外协业务请使用专属逆操作",
        )
    if original.transaction_type == "SALE_OUT":
        receivable = db.scalar(
            select(Receivable)
            .where(Receivable.related_stock_transaction_id == original.id)
        )
        if receivable:
            allocated = float(receivable.settled_amount or 0)
            if allocated > 1e-9:
                raise HTTPException(
                    409,
                    f"该出库已关联应收 {receivable.receivable_no}，已核销 {allocated:.2f}；"
                    "请先处理财务核销再冲销库存",
                )
            receivable.status = "CANCELLED"
            receivable.notes = (receivable.notes or "") + f"；因冲销 {original.transaction_no} 而取消"
        # 冲销守卫：恢复发货数量后，"客户已退数量"不能超过"累计发货"，
        # 否则说明这批货物已经发生退货，直接冲销会让退货账目悬空。
        for order_item_id, delta in _sale_out_reversal_deltas(db, original).items():
            order_item = db.get(SalesOrderItem, order_item_id)
            if not order_item:
                continue
            shipped_after = int(order_item.shipped_quantity or 0) - delta["original"]
            replacement_after = int(order_item.replacement_shipped_quantity or 0) - delta["replacement"]
            if shipped_after + replacement_after < int(order_item.returned_quantity or 0):
                raise HTTPException(
                    409,
                    f"{order_item.product.sku} 已发生退货 {int(order_item.returned_quantity or 0)} 件；"
                    "直接冲销会使已退数量超过累计发货，请先处理退货记录",
                )
    changes = []
    for line in original.lines:
        changes.append((line.item, -line.quantity_change, line.unit_cost))
    reversal_tx = create_transaction(
        db,
        "REVERSAL",
        changes,
        f"冲销 {original.transaction_no}",
        related_order_id=original.related_order_id,
        related_production_run_id=original.related_production_run_id,
        occurred_at=datetime.now(),
    )
    reversal_tx.reversal_of_transaction_id = original.id
    original.reversed_by_transaction_id = reversal_tx.id
    original.status = "REVERSED"
    if original.transaction_type == "SALE_OUT" and original.related_order_id:
        order = db.get(SalesOrder, original.related_order_id)
        for order_item_id, delta in _sale_out_reversal_deltas(db, original).items():
            order_item = db.get(SalesOrderItem, order_item_id)
            if not order_item:
                continue
            order_item.shipped_quantity = max(
                int(order_item.shipped_quantity or 0) - delta["original"], 0
            )
            order_item.replacement_shipped_quantity = max(
                int(order_item.replacement_shipped_quantity or 0) - delta["replacement"], 0
            )
            order_item.replacement_pending_quantity = (
                int(order_item.replacement_pending_quantity or 0) + delta["replacement"]
            )
        # 冲销让需求重新出现时，已完结订单必须重开，否则后续出库会被状态检查拒绝。
        if order and order.status == "FULFILLED" and any(
            int(line.shipped_quantity or 0) < int(line.quantity)
            or int(line.replacement_pending_quantity or 0) > 0
            for line in db.scalars(
                select(SalesOrderItem).where(SalesOrderItem.order_id == order.id)
            ).all()
        ):
            order.status = "PARTIALLY_SHIPPED"
    affected_products = {line.item_id for line in original.lines if line.item.kind == "PRODUCT"}
    if affected_products:
        rebalance_product_reservations(db, affected_products)
    recalculate_production_plan(db)
    db.commit()
    return transaction_dict(reversal_tx)


@app.post("/api/stock/reconcile", status_code=201)
def reconcile_stock(
    payload: StockReconciliationPayload,
    db: Session = Depends(get_db),
):
    item_ids = [line.item_id for line in payload.items]
    items = {
        item.id: item
        for item in db.scalars(
            select(InventoryItem)
            .where(
                InventoryItem.id.in_(item_ids),
                InventoryItem.active.is_(True),
                InventoryItem.kind.in_(("PART", "PRODUCT")),
            )
        ).all()
    }
    if len(items) != len(item_ids):
        raise HTTPException(404, "对账中有物料不存在或已停用")
    discrepancies = []
    adjustment_changes: list[tuple[InventoryItem, float, float]] = []
    for requested in payload.items:
        item = items[requested.item_id]
        system_qty = float(item.stock_qty)
        physical_qty = float(requested.physical_count)
        diff = round(physical_qty - system_qty, 6)
        if abs(diff) > 1e-9:
            discrepancies.append({
                "item_id": item.id,
                "sku": item.sku,
                "name": item.name,
                "unit": item.unit,
                "system_quantity": system_qty,
                "physical_quantity": physical_qty,
                "difference": diff,
            })
            adjustment_changes.append((item, diff, item.cost_price))
    transaction = None
    if adjustment_changes:
        transaction = create_transaction(
            db,
            "MANUAL_IN",
            adjustment_changes,
            payload.notes or "库存对账调整",
            occurred_at=datetime.now(),
        )
    affected_products = {item_id for item_id in item_ids if items[item_id].kind == "PRODUCT"}
    if affected_products:
        rebalance_product_reservations(db, affected_products)
    recalculate_production_plan(db)
    db.commit()
    return {
        "reconciled_count": len(payload.items),
        "discrepancy_count": len(discrepancies),
        "discrepancies": discrepancies,
        "transaction_id": transaction.id if transaction else None,
        "transaction_no": transaction.transaction_no if transaction else None,
    }


@app.get("/api/backups")
def backups(request: Request):
    require_admin(request)
    return list_backup_archives()


def receivable_dict(row: Receivable) -> dict:
    return {
        "id": row.id,
        "receivable_no": row.receivable_no,
        "order_id": row.order_id,
        "related_stock_transaction_id": row.related_stock_transaction_id,
        "customer_name": row.customer_name,
        "amount": float(row.amount),
        "settled_amount": float(row.settled_amount or 0),
        "remaining_amount": float(row.amount) - float(row.settled_amount or 0),
        "status": row.status,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }


@app.get("/api/finance/receivables")
def list_receivables(
    status: str | None = None,
    keyword: str = "",
    db: Session = Depends(get_db),
):
    query = select(Receivable)
    if status and status.strip():
        query = query.where(Receivable.status == status.strip().upper())
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(or_(
            Receivable.receivable_no.ilike(token),
            Receivable.customer_name.ilike(token),
        ))
    rows = db.scalars(query.order_by(Receivable.created_at.desc())).all()
    return [receivable_dict(row) for row in rows]


def payment_dict(row: Payment) -> dict:
    return {
        "id": row.id,
        "payment_no": row.payment_no,
        "customer_name": row.customer_name,
        "amount": float(row.amount),
        "allocated_amount": float(row.allocated_amount or 0),
        "remaining_amount": float(row.amount) - float(row.allocated_amount or 0),
        "payment_date": row.payment_date.isoformat(),
        "method": row.method,
        "notes": row.notes,
        "created_at": row.created_at.isoformat(),
        "allocations": [
            {
                "id": alloc.id,
                "receivable_id": alloc.receivable_id,
                "amount": float(alloc.amount),
            }
            for alloc in row.allocations
        ],
    }


@app.get("/api/finance/payments")
def list_payments(
    keyword: str = "",
    start_date: date | None = None,
    end_date: date | None = None,
    db: Session = Depends(get_db),
):
    query = select(Payment).options(selectinload(Payment.allocations))
    if keyword.strip():
        token = f"%{keyword.strip()}%"
        query = query.where(or_(
            Payment.payment_no.ilike(token),
            Payment.customer_name.ilike(token),
        ))
    if start_date:
        query = query.where(Payment.payment_date >= start_date)
    if end_date:
        query = query.where(Payment.payment_date <= end_date)
    rows = db.scalars(query.order_by(Payment.payment_date.desc(), Payment.id.desc())).all()
    return [payment_dict(row) for row in rows]


@app.post("/api/finance/payments", status_code=201)
def create_payment(
    payload: PaymentPayload,
    db: Session = Depends(get_db),
):
    payment = Payment(
        payment_no=serial("PAY"),
        customer_name=payload.customer_name.strip(),
        amount=round(payload.amount, 2),
        payment_date=payload.payment_date,
        method=payload.method,
        notes=payload.notes.strip(),
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)
    return payment_dict(payment)


@app.post("/api/finance/payments/{payment_id}/allocate", status_code=201)
def allocate_payment(
    payment_id: int,
    payload: PaymentAllocationPayload,
    db: Session = Depends(get_db),
):
    payment = db.scalar(
        select(Payment)
        .where(Payment.id == payment_id)
        .options(selectinload(Payment.allocations))
    )
    if not payment:
        raise HTTPException(404, "付款记录不存在")
    receivable = db.scalar(
        select(Receivable)
        .where(Receivable.id == payload.receivable_id)
        .options(selectinload(Receivable.allocations))
    )
    if not receivable:
        raise HTTPException(404, "应收记录不存在")
    payment_remaining = float(payment.amount) - float(payment.allocated_amount or 0)
    receivable_remaining = float(receivable.amount) - float(receivable.settled_amount or 0)
    if payload.amount > payment_remaining + 1e-9:
        raise HTTPException(409, f"付款剩余可分配 {payment_remaining:.2f}，不足以分配 {payload.amount:.2f}")
    if payload.amount > receivable_remaining + 1e-9:
        raise HTTPException(409, f"应收剩余可核销 {receivable_remaining:.2f}，不足以核销 {payload.amount:.2f}")
    allocation = PaymentAllocation(
        payment_id=payment.id,
        receivable_id=receivable.id,
        amount=round(payload.amount, 2),
    )
    db.add(allocation)
    payment.allocated_amount = round(float(payment.allocated_amount or 0) + payload.amount, 2)
    receivable.settled_amount = round(float(receivable.settled_amount or 0) + payload.amount, 2)
    if float(receivable.settled_amount) >= float(receivable.amount) - 1e-9:
        receivable.status = "SETTLED"
    elif float(receivable.settled_amount) > 0:
        receivable.status = "PARTIAL"
    db.commit()
    db.refresh(payment)
    return payment_dict(payment)


@app.get("/api/users")
def list_users(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    rows = db.scalars(
        select(User).where(User.active.is_(True)).order_by(User.id)
    ).all()
    return [
        {
            "id": row.id,
            "username": row.username,
            "display_name": row.display_name,
            "role": row.role,
            "active": row.active,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@app.post("/api/users", status_code=201)
def create_user(payload: UserPayload, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    existing = db.scalar(select(User).where(User.username == payload.username.strip()))
    if existing:
        raise HTTPException(409, "用户名已存在")
    user = User(
        username=payload.username.strip(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name.strip(),
        role=payload.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return {
        "id": user.id,
        "username": user.username,
        "display_name": user.display_name,
        "role": user.role,
    }


@app.put("/api/users/{user_id}")
def update_user(user_id: int, payload: UserUpdatePayload, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    user.display_name = payload.display_name.strip()
    user.role = payload.role
    user.active = payload.active
    if payload.password:
        user.password_hash = hash_password(payload.password)
    db.commit()
    return {"ok": True}


@app.delete("/api/users/{user_id}")
def delete_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "用户不存在")
    user.active = False
    db.commit()
    return {"ok": True}


@app.post("/api/backups", status_code=201)
def create_backup(request: Request, db: Session = Depends(get_db)):
    require_admin(request)
    return create_backup_archive(db)


@app.get("/api/backups/{filename}/download")
def download_backup(filename: str, request: Request):
    require_admin(request)
    try:
        path = resolve_backup_file(filename)
    except BackupError as error:
        raise HTTPException(400, str(error)) from error
    except FileNotFoundError as error:
        raise HTTPException(404, "备份文件不存在") from error
    return FileResponse(path, media_type="application/zip", filename=path.name)


@app.post("/api/backups/{filename}/restore")
def restore_backup(filename: str, payload: BackupRestorePayload, request: Request, db: Session = Depends(get_db)):
    require_admin(request)
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
