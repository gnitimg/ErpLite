from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from sqlalchemy import Date, DateTime
from sqlalchemy.orm import Session

from .database import PROJECT_ROOT
from .models import InventoryItem, ProductBomItem, SalesOrder, SalesOrderItem, StockTransaction, StockTransactionItem


BACKUP_DIRECTORY = PROJECT_ROOT / "backups"
BACKUP_SCHEMA_VERSION = 1
BACKUP_TABLES = (
    InventoryItem.__table__,
    SalesOrder.__table__,
    ProductBomItem.__table__,
    SalesOrderItem.__table__,
    StockTransaction.__table__,
    StockTransactionItem.__table__,
)
DELETE_TABLES = (
    StockTransactionItem.__table__,
    ProductBomItem.__table__,
    SalesOrderItem.__table__,
    StockTransaction.__table__,
    SalesOrder.__table__,
    InventoryItem.__table__,
)


class BackupError(ValueError):
    pass


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _decode_row(table, row: dict[str, Any]) -> dict[str, Any]:
    known_columns = {column.name: column for column in table.columns}
    if set(row) - set(known_columns):
        raise BackupError(f"备份中的 {table.name} 表包含未知字段")
    result: dict[str, Any] = {}
    for name, value in row.items():
        column = known_columns[name]
        try:
            if value is not None and isinstance(value, str):
                if isinstance(column.type, DateTime):
                    value = datetime.fromisoformat(value)
                elif isinstance(column.type, Date):
                    value = date.fromisoformat(value)
        except ValueError as error:
            raise BackupError(f"备份中的 {table.name}.{name} 日期格式不正确") from error
        result[name] = value
    return result


def _load_archive(path: Path) -> dict[str, Any]:
    try:
        with ZipFile(path, "r") as archive:
            payload = json.loads(archive.read("backup.json").decode("utf-8"))
    except (BadZipFile, KeyError, json.JSONDecodeError, UnicodeDecodeError) as error:
        raise BackupError("备份文件已损坏或格式不正确") from error

    if payload.get("schema_version") != BACKUP_SCHEMA_VERSION:
        raise BackupError("备份版本与当前系统不兼容")
    if not isinstance(payload.get("created_at"), str):
        raise BackupError("备份缺少有效的创建时间")
    if payload.get("backup_type", "MANUAL") not in {"MANUAL", "PRE_RESTORE"}:
        raise BackupError("备份类型无效")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise BackupError("备份缺少数据表内容")
    required_names = {table.name for table in BACKUP_TABLES}
    if set(tables) != required_names:
        raise BackupError("备份包含的数据表与当前系统不一致")
    for table_name, rows in tables.items():
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BackupError(f"备份中的 {table_name} 表格式不正确")
    return payload


def _metadata(path: Path, payload: dict[str, Any]) -> dict[str, Any]:
    table_counts = {name: len(rows) for name, rows in payload["tables"].items()}
    return {
        "filename": path.name,
        "created_at": payload["created_at"],
        "backup_type": payload.get("backup_type", "MANUAL"),
        "source_backup": payload.get("source_backup"),
        "size_bytes": path.stat().st_size,
        "table_counts": table_counts,
        "total_records": sum(table_counts.values()),
    }


def resolve_backup_file(filename: str) -> Path:
    if Path(filename).name != filename or not filename.startswith("erp-") or not filename.endswith(".zip"):
        raise BackupError("备份文件名无效")
    path = (BACKUP_DIRECTORY / filename).resolve()
    if path.parent != BACKUP_DIRECTORY.resolve():
        raise BackupError("备份文件路径无效")
    if not path.is_file():
        raise FileNotFoundError(filename)
    return path


def list_backup_archives() -> list[dict[str, Any]]:
    if not BACKUP_DIRECTORY.exists():
        return []
    backups: list[dict[str, Any]] = []
    for path in BACKUP_DIRECTORY.glob("erp-*.zip"):
        try:
            backups.append(_metadata(path, _load_archive(path)))
        except (BackupError, OSError):
            continue
    return sorted(backups, key=lambda item: item["created_at"], reverse=True)


def create_backup_archive(
    db: Session,
    backup_type: str = "MANUAL",
    source_backup: str | None = None,
) -> dict[str, Any]:
    created_at = datetime.now().astimezone()
    tables: dict[str, list[dict[str, Any]]] = {}
    for table in BACKUP_TABLES:
        rows = db.execute(table.select().order_by(table.c.id)).mappings().all()
        tables[table.name] = [{key: _json_value(value) for key, value in row.items()} for row in rows]

    payload = {
        "schema_version": BACKUP_SCHEMA_VERSION,
        "created_at": created_at.isoformat(),
        "backup_type": backup_type,
        "source_backup": source_backup,
        "database_dialect": db.bind.dialect.name if db.bind else "unknown",
        "tables": tables,
    }
    prefix = "erp-pre-restore" if backup_type == "PRE_RESTORE" else "erp-backup"
    filename = f"{prefix}-{created_at.strftime('%Y%m%d-%H%M%S-%f')}.zip"
    BACKUP_DIRECTORY.mkdir(parents=True, exist_ok=True)
    target = BACKUP_DIRECTORY / filename
    temporary = target.with_suffix(".zip.tmp")
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            archive.writestr("backup.json", json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
        temporary.replace(target)
    finally:
        if temporary.exists():
            temporary.unlink()
    return _metadata(target, payload)


def restore_backup_archive(db: Session, path: Path) -> dict[str, Any]:
    payload = _load_archive(path)
    decoded_tables: dict[str, list[dict[str, Any]]] = {}
    table_by_name = {table.name: table for table in BACKUP_TABLES}
    for table_name, rows in payload["tables"].items():
        decoded_tables[table_name] = [_decode_row(table_by_name[table_name], row) for row in rows]

    safety_backup = create_backup_archive(db, "PRE_RESTORE", path.name)
    db.rollback()
    try:
        for table in DELETE_TABLES:
            db.execute(table.delete())
        for table in BACKUP_TABLES:
            rows = decoded_tables[table.name]
            if rows:
                db.execute(table.insert(), rows)
        db.commit()
    except Exception:
        db.rollback()
        raise

    restored = _metadata(path, payload)
    return {
        "ok": True,
        "restored_backup": restored,
        "safety_backup": safety_backup,
        "restored_records": restored["total_records"],
    }
