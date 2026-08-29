import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, sessionmaker


PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DEFAULT_MYSQL_PASSWORD = "LiteErp@2026!"


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().lower() in {"1", "true", "yes"}


def _is_loopback(host: str | None) -> bool:
    return (host or "").strip().lower() in {"127.0.0.1", "localhost", "::1"}


def resolve_database_url() -> str:
    """解析数据库配置，并在 production 对外部凭据执行 fail-close。"""
    production = os.getenv("ERP_ENV", "dev").strip().lower() == "production"
    bundled_local = _enabled("ERP_BUNDLED_LOCAL_MYSQL")
    configured_url = os.getenv("ERP_DATABASE_URL")

    if configured_url:
        parsed = make_url(configured_url)
        if production:
            if not parsed.password:
                raise RuntimeError("生产环境 ERP_DATABASE_URL 必须包含数据库密码")
            default_is_allowed = bundled_local and _is_loopback(parsed.host)
            if parsed.password == DEFAULT_MYSQL_PASSWORD and not default_is_allowed:
                raise RuntimeError("生产环境 ERP_DATABASE_URL 不能使用公开默认数据库密码")
        return configured_url

    host = os.getenv("ERP_MYSQL_HOST", "127.0.0.1")
    port = os.getenv("ERP_MYSQL_PORT", "3306")
    database = os.getenv("ERP_MYSQL_DATABASE", "lite_erp")
    user = quote_plus(os.getenv("ERP_MYSQL_USER", "lite_erp"))
    password_raw = os.getenv("ERP_MYSQL_PASSWORD")
    if production:
        default_is_allowed = bundled_local and _is_loopback(host)
        if not password_raw:
            raise RuntimeError("生产环境必须显式设置 ERP_MYSQL_PASSWORD")
        if password_raw == DEFAULT_MYSQL_PASSWORD and not default_is_allowed:
            raise RuntimeError("外部生产数据库不能使用公开默认数据库密码")
    password = quote_plus(password_raw or DEFAULT_MYSQL_PASSWORD)
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{database}?charset=utf8mb4"


DATABASE_URL = resolve_database_url()

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


def run_migrations() -> None:
    """执行正式 Alembic 迁移；已有旧库先补齐历史兼容列。"""
    inspector = inspect(engine)
    if "inventory_items" in inspector.get_table_names():
        ensure_schema_compatibility()
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "backend" / "alembic"))
    config.attributes["connection"] = engine
    command.upgrade(config, "head")


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
        "inventory_items.daily_capacity": (
            "daily_capacity",
            "ALTER TABLE inventory_items ADD COLUMN daily_capacity INT NOT NULL DEFAULT 0",
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
        "production_settings.print_header_mode": (
            "print_header_mode",
            "ALTER TABLE production_settings ADD COLUMN print_header_mode VARCHAR(10) NOT NULL DEFAULT 'none'",
        ),
        "production_settings.print_company_name": (
            "print_company_name",
            "ALTER TABLE production_settings ADD COLUMN print_company_name VARCHAR(100) NOT NULL DEFAULT ''",
        ),
        "production_settings.print_logo": (
            "print_logo",
            "ALTER TABLE production_settings ADD COLUMN print_logo TEXT",
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
