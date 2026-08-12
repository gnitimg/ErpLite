import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

MYSQL_HOST = os.getenv("ERP_MYSQL_HOST", "127.0.0.1")
MYSQL_PORT = os.getenv("ERP_MYSQL_PORT", "3306")
MYSQL_DATABASE = os.getenv("ERP_MYSQL_DATABASE", "lite_erp")
MYSQL_USER = quote_plus(os.getenv("ERP_MYSQL_USER", "lite_erp"))
MYSQL_PASSWORD = quote_plus(os.getenv("ERP_MYSQL_PASSWORD", "LiteErp@2026!"))
DATABASE_URL = os.getenv(
    "ERP_DATABASE_URL",
    f"mysql+pymysql://{MYSQL_USER}:{MYSQL_PASSWORD}@{MYSQL_HOST}:{MYSQL_PORT}/{MYSQL_DATABASE}?charset=utf8mb4",
)

connect_args = {"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, connect_args=connect_args, future=True, pool_pre_ping=True, pool_recycle=1800)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def ensure_schema_compatibility() -> None:
    """为无迁移框架的本机版本补齐新增列，同时兼容已有 MySQL 数据。"""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    additions = {
        "inventory_items": (
            "supply_mode",
            "ALTER TABLE inventory_items ADD COLUMN supply_mode VARCHAR(20) NOT NULL DEFAULT 'STOCK'",
        ),
        "inventory_items.sample_stock_qty": (
            "sample_stock_qty",
            "ALTER TABLE inventory_items ADD COLUMN sample_stock_qty INT NOT NULL DEFAULT 300",
        ),
        "sales_order_items": (
            "reserved_quantity",
            "ALTER TABLE sales_order_items ADD COLUMN reserved_quantity FLOAT NOT NULL DEFAULT 0",
        ),
        "sales_order_items.reference_price": (
            "reference_price",
            "ALTER TABLE sales_order_items ADD COLUMN reference_price FLOAT NOT NULL DEFAULT 0",
        ),
        "sales_orders.required_date": (
            "required_date",
            "ALTER TABLE sales_orders ADD COLUMN required_date DATE NULL",
        ),
    }
    with engine.begin() as connection:
        for addition_key, (column_name, statement) in additions.items():
            table_name = addition_key.split(".", 1)[0]
            if table_name not in tables:
                continue
            columns = {column["name"] for column in inspector.get_columns(table_name)}
            if column_name not in columns:
                connection.execute(text(statement))
        if "sales_orders" in tables:
            connection.execute(text("UPDATE sales_orders SET required_date = order_date WHERE required_date IS NULL"))
        if "inventory_items" in tables:
            connection.execute(text(
                "ALTER TABLE inventory_items "
                "ALTER COLUMN sample_stock_qty SET DEFAULT 300"
            ))
        if "sales_order_items" in tables and "inventory_items" in tables:
            if engine.dialect.name == "mysql":
                connection.execute(text(
                    "UPDATE sales_order_items AS order_item "
                    "JOIN inventory_items AS product ON product.id = order_item.product_id "
                    "SET order_item.reference_price = product.sale_price "
                    "WHERE order_item.reference_price IS NULL OR order_item.reference_price = 0"
                ))
            else:
                connection.execute(text(
                    "UPDATE sales_order_items SET reference_price = COALESCE(("
                    "SELECT sale_price FROM inventory_items WHERE inventory_items.id = sales_order_items.product_id"
                    "), unit_price) WHERE reference_price IS NULL OR reference_price = 0"
                ))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
