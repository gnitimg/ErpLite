import os
from pathlib import Path
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
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


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
