from contextlib import asynccontextmanager
import base64
import os
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .database import Base, SessionLocal, engine, get_db
from .models import InventoryItem, ProductBomItem, SalesOrder, SalesOrderItem, StockTransaction, StockTransactionItem
from .schemas import LoginPayload, OrderPayload, PartPayload, ProductPayload, StockPayload
from .services import create_transaction, ensure_sku_available, item_dict, load_order, order_dict, seed_demo, serial, transaction_dict


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_demo(db)
    yield


app = FastAPI(title="轻量 ERP API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3333", "http://127.0.0.1:3333", "http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def find_item(db: Session, item_id: int, kind: str | None = None) -> InventoryItem:
    item = db.get(InventoryItem, item_id)
    if not item or not item.active or (kind and item.kind != kind):
        raise HTTPException(404, "物料不存在")
    return item


def list_items(db: Session, kind: str, keyword: str = "", include_bom: bool = False) -> list[dict]:
    query = select(InventoryItem).where(InventoryItem.kind == kind, InventoryItem.active.is_(True))
    if keyword:
        token = f"%{keyword.strip()}%"
        query = query.where(or_(InventoryItem.sku.ilike(token), InventoryItem.name.ilike(token)))
    if include_bom:
        query = query.options(selectinload(InventoryItem.bom_components).selectinload(ProductBomItem.part))
    items = db.scalars(query.order_by(InventoryItem.id.desc())).all()
    return [item_dict(item, include_bom) for item in items]


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "lite-erp"}


@app.get("/api/v1/auth/captcha")
def captcha():
    svg = """<svg xmlns='http://www.w3.org/2000/svg' width='100' height='40'><rect width='100' height='40' rx='5' fill='#eef2ff'/><path d='M5 30L95 8M12 8L88 34' stroke='#b8c4ef' stroke-width='1'/><text x='50' y='27' text-anchor='middle' font-family='Arial' font-size='21' font-weight='700' letter-spacing='4' fill='#3155d9'>1234</text></svg>"""
    encoded = base64.b64encode(svg.encode()).decode()
    return {"code": 0, "data": f"data:image/svg+xml;base64,{encoded}", "message": "success"}


@app.post("/api/v1/auth/login")
def login(payload: LoginPayload):
    username = os.getenv("ERP_ADMIN_USER", "admin")
    password = os.getenv("ERP_ADMIN_PASSWORD", "12345678")
    if payload.username != username or payload.password != password or payload.code.strip() != "1234":
        raise HTTPException(401, "用户名、密码或验证码错误")
    return {"code": 0, "data": {"token": "lite-erp-local-admin"}, "message": "success"}


@app.get("/api/v1/users/me")
def current_user():
    return {"code": 0, "data": {"username": "仓库管理员", "roles": ["admin"], "permissions": []}, "message": "success"}


@app.get("/api/dashboard")
def dashboard(db: Session = Depends(get_db)):
    active = InventoryItem.active.is_(True)
    part_count = db.scalar(select(func.count()).select_from(InventoryItem).where(active, InventoryItem.kind == "PART")) or 0
    product_count = db.scalar(select(func.count()).select_from(InventoryItem).where(active, InventoryItem.kind == "PRODUCT")) or 0
    low_stock = db.scalar(select(func.count()).select_from(InventoryItem).where(active, InventoryItem.stock_qty <= InventoryItem.min_stock)) or 0
    pending_orders = db.scalar(select(func.count()).select_from(SalesOrder).where(SalesOrder.status.in_(["DRAFT", "CONFIRMED"]))) or 0
    inventory_value = db.scalar(select(func.sum(InventoryItem.stock_qty * InventoryItem.cost_price)).where(active)) or 0
    recent_txs = db.scalars(
        select(StockTransaction)
        .options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item), selectinload(StockTransaction.related_order))
        .order_by(StockTransaction.occurred_at.desc()).limit(6)
    ).all()
    low_items = db.scalars(select(InventoryItem).where(active, InventoryItem.stock_qty <= InventoryItem.min_stock).order_by(InventoryItem.stock_qty)).all()
    return {
        "metrics": {"parts": part_count, "products": product_count, "low_stock": low_stock, "pending_orders": pending_orders, "inventory_value": inventory_value},
        "recent_transactions": [transaction_dict(tx) for tx in recent_txs],
        "low_stock_items": [item_dict(item) for item in low_items[:8]],
    }


@app.get("/api/parts")
def parts(keyword: str = "", db: Session = Depends(get_db)):
    return list_items(db, "PART", keyword)


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


@app.get("/api/products")
def products(keyword: str = "", db: Session = Depends(get_db)):
    return list_items(db, "PRODUCT", keyword, True)


def save_product(db: Session, payload: ProductPayload, product: InventoryItem | None = None) -> InventoryItem:
    ensure_sku_available(db, payload.sku, product.id if product else None)
    part_ids = [line.part_id for line in payload.components]
    parts = {part.id: part for part in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(part_ids), InventoryItem.kind == "PART", InventoryItem.active.is_(True))).all()} if part_ids else {}
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
    product.bom_components = [ProductBomItem(part_id=line.part_id, quantity=line.quantity) for line in payload.components]
    db.commit()
    return db.scalar(select(InventoryItem).where(InventoryItem.id == product.id).options(selectinload(InventoryItem.bom_components).selectinload(ProductBomItem.part)))


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


@app.get("/api/inventory")
def inventory(kind: str | None = None, low_stock: bool = False, keyword: str = "", db: Session = Depends(get_db)):
    query = select(InventoryItem).where(InventoryItem.active.is_(True))
    if kind in {"PART", "PRODUCT"}:
        query = query.where(InventoryItem.kind == kind)
    if low_stock:
        query = query.where(InventoryItem.stock_qty <= InventoryItem.min_stock)
    if keyword:
        token = f"%{keyword.strip()}%"
        query = query.where(or_(InventoryItem.sku.ilike(token), InventoryItem.name.ilike(token)))
    items = db.scalars(query.order_by(InventoryItem.kind, InventoryItem.sku)).all()
    return [item_dict(item) for item in items]


@app.get("/api/stock/transactions")
def stock_transactions(limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db)):
    txs = db.scalars(
        select(StockTransaction)
        .options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item), selectinload(StockTransaction.related_order))
        .order_by(StockTransaction.occurred_at.desc()).limit(limit)
    ).all()
    return [transaction_dict(tx) for tx in txs]


@app.post("/api/stock/inbound", status_code=201)
def inbound(payload: StockPayload, db: Session = Depends(get_db)):
    item = find_item(db, payload.item_id)
    changes: list[tuple[InventoryItem, float, float]] = []
    tx_type = "PURCHASE_IN" if item.kind == "PART" else "MANUAL_IN"
    if item.kind == "PRODUCT" and payload.consume_bom:
        product = db.scalar(select(InventoryItem).where(InventoryItem.id == item.id).options(selectinload(InventoryItem.bom_components).selectinload(ProductBomItem.part)))
        if not product.bom_components:
            raise HTTPException(409, "产品还没有 BOM，不能按 BOM 生产入库")
        changes.extend((line.part, -line.quantity * payload.quantity, line.part.cost_price) for line in product.bom_components)
        tx_type = "ASSEMBLY_IN"
    changes.append((item, payload.quantity, payload.unit_cost or item.cost_price))
    tx = create_transaction(db, tx_type, changes, payload.notes)
    db.commit()
    tx = db.scalar(select(StockTransaction).where(StockTransaction.id == tx.id).options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item), selectinload(StockTransaction.related_order)))
    return transaction_dict(tx)


@app.post("/api/stock/outbound", status_code=201)
def outbound(payload: StockPayload, db: Session = Depends(get_db)):
    item = find_item(db, payload.item_id)
    tx = create_transaction(db, "MANUAL_OUT", [(item, -payload.quantity, item.cost_price)], payload.notes)
    db.commit()
    tx = db.scalar(select(StockTransaction).where(StockTransaction.id == tx.id).options(selectinload(StockTransaction.lines).selectinload(StockTransactionItem.item), selectinload(StockTransaction.related_order)))
    return transaction_dict(tx)


@app.get("/api/orders")
def orders(status: str | None = None, db: Session = Depends(get_db)):
    query = select(SalesOrder).options(selectinload(SalesOrder.items).selectinload(SalesOrderItem.product))
    if status:
        query = query.where(SalesOrder.status == status)
    rows = db.scalars(query.order_by(SalesOrder.order_date.desc(), SalesOrder.id.desc())).all()
    return [order_dict(order) for order in rows]


@app.post("/api/orders", status_code=201)
def create_order(payload: OrderPayload, db: Session = Depends(get_db)):
    ids = [line.product_id for line in payload.items]
    products = {item.id: item for item in db.scalars(select(InventoryItem).where(InventoryItem.id.in_(ids), InventoryItem.kind == "PRODUCT", InventoryItem.active.is_(True))).all()}
    if len(products) != len(ids):
        raise HTTPException(400, "客单中包含无效产品")
    order = SalesOrder(
        order_no=serial("SO"), customer_name=payload.customer_name, customer_phone=payload.customer_phone,
        customer_address=payload.customer_address, order_date=payload.order_date, notes=payload.notes, status="DRAFT"
    )
    order.items = [
        SalesOrderItem(product_id=line.product_id, quantity=line.quantity, unit_price=line.unit_price, line_total=round(line.quantity * line.unit_price, 2))
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
    db.commit()
    return order_dict(order)


@app.post("/api/orders/{order_id}/fulfill")
def fulfill_order(order_id: int, db: Session = Depends(get_db)):
    order = load_order(db, order_id)
    if order.status not in {"DRAFT", "CONFIRMED"}:
        raise HTTPException(409, "当前客单不能出库")
    tx = create_transaction(db, "SALE_OUT", [(line.product, -line.quantity, line.product.cost_price) for line in order.items], f"客单 {order.order_no} 出库", order.id)
    order.status = "FULFILLED"
    db.commit()
    return {"order": order_dict(order), "transaction_id": tx.id}


@app.post("/api/orders/{order_id}/cancel")
def cancel_order(order_id: int, db: Session = Depends(get_db)):
    order = load_order(db, order_id)
    if order.status == "FULFILLED":
        raise HTTPException(409, "已出库客单不能直接取消")
    order.status = "CANCELLED"
    db.commit()
    return order_dict(order)


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
