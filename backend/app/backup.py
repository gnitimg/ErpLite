from __future__ import annotations

from datetime import date, datetime
import json
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

from sqlalchemy import Date, DateTime
from sqlalchemy.orm import Session

from .database import PROJECT_ROOT
from .models import (
    CustomerCredit,
    ExternalProcessingBatch,
    InventoryItem,
    Mold,
    OperationLog,
    OrderReturn,
    OrderShipmentAllocation,
    Payment,
    PaymentAllocation,
    ProductBomItem,
    ProductMold,
    ProductionAllocation,
    ProductionCalendarException,
    ProductionCapability,
    ProductionLine,
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


BACKUP_DIRECTORY = PROJECT_ROOT / "backups"
BACKUP_SCHEMA_VERSION = 22
BACKUP_TABLES = (
    InventoryItem.__table__,
    SalesOrder.__table__,
    ProductBomItem.__table__,
    SalesOrderItem.__table__,
    ProductionLine.__table__,
    ProductionSetting.__table__,
    Mold.__table__,
    ProductMold.__table__,
    ProductionCapability.__table__,
    StockReservation.__table__,
    ProductionRun.__table__,
    ProductionAllocation.__table__,
    ProductionMaterialReservation.__table__,
    StockTransaction.__table__,
    StockTransactionItem.__table__,
    OrderShipmentAllocation.__table__,
    OrderReturn.__table__,
    ExternalProcessingBatch.__table__,
    PurchaseCommitment.__table__,
    ProductionCalendarException.__table__,
    Receivable.__table__,
    Payment.__table__,
    PaymentAllocation.__table__,
    CustomerCredit.__table__,
    User.__table__,
    OperationLog.__table__,
)
DELETE_TABLES = (
    CustomerCredit.__table__,
    PaymentAllocation.__table__,
    Payment.__table__,
    Receivable.__table__,
    User.__table__,
    ProductionCalendarException.__table__,
    PurchaseCommitment.__table__,
    ExternalProcessingBatch.__table__,
    OrderReturn.__table__,
    OrderShipmentAllocation.__table__,
    ProductionAllocation.__table__,
    ProductionMaterialReservation.__table__,
    StockTransactionItem.__table__,
    OperationLog.__table__,
    StockReservation.__table__,
    ProductionRun.__table__,
    ProductionCapability.__table__,
    ProductionSetting.__table__,
    ProductMold.__table__,
    ProductBomItem.__table__,
    SalesOrderItem.__table__,
    StockTransaction.__table__,
    SalesOrder.__table__,
    Mold.__table__,
    ProductionLine.__table__,
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

    schema_version = payload.get("schema_version")
    if schema_version not in set(range(1, BACKUP_SCHEMA_VERSION + 1)):
        raise BackupError("备份版本与当前系统不兼容")
    if not isinstance(payload.get("created_at"), str):
        raise BackupError("备份缺少有效的创建时间")
    if payload.get("backup_type", "MANUAL") not in {"MANUAL", "PRE_RESTORE"}:
        raise BackupError("备份类型无效")
    tables = payload.get("tables")
    if not isinstance(tables, dict):
        raise BackupError("备份缺少数据表内容")
    # 兼容流程和 ETA 改造前的快照，并为新增字段提供安全默认值。
    if schema_version in {1, 2, 3, 4, 5}:
        tables.setdefault("operation_logs", [])
        for row in tables.get("inventory_items", []):
            row.setdefault("supply_mode", "STOCK")
            row.setdefault("sample_stock_qty", 0)
            row.setdefault("daily_capacity", 0)
            row.setdefault("mold_count", 1 if row.get("kind") == "PRODUCT" else 0)
        for row in tables.get("sales_orders", []):
            row.setdefault("required_date", row.get("order_date"))
            row.setdefault("estimated_completion_at", None)
            row.setdefault("eta_calculated_at", None)
            row.setdefault("eta_reliable", False)
            row.setdefault("eta_note", "")
        reference_prices = {
            row.get("id"): row.get("sale_price", 0) for row in tables.get("inventory_items", [])
        }
        for row in tables.get("sales_order_items", []):
            row.setdefault("reserved_quantity", 0)
            row.setdefault("reference_price", reference_prices.get(row.get("product_id"), row.get("unit_price", 0)))
            row.setdefault("production_required_quantity", 0)
            row.setdefault("estimated_completion_at", None)
            row.setdefault("eta_reliable", False)
            row.setdefault("eta_note", "")
        tables.setdefault("production_lines", [])
        tables.setdefault("molds", [])
        tables.setdefault("product_molds", [])
        tables.setdefault("production_capabilities", [])
        tables.setdefault("production_runs", [])
        tables.setdefault("production_allocations", [])
        for row in tables["production_runs"]:
            row.setdefault("mold_slot", 1)
        if "stock_reservations" not in tables:
            tables["stock_reservations"] = [
                {
                    "id": index + 1,
                    "order_item_id": row["id"],
                    "product_id": row["product_id"],
                    "quantity": row.get("reserved_quantity", 0),
                    "status": "ACTIVE" if row.get("reserved_quantity", 0) > 0 else "RELEASED",
                    "created_at": payload["created_at"],
                    "updated_at": payload["created_at"],
                }
                for index, row in enumerate(tables.get("sales_order_items", []))
            ]
    if schema_version in {1, 2, 3, 4, 5, 6}:
        legacy_lines = sorted(
            tables.get("production_lines", []),
            key=lambda row: row.get("id", 0),
        )
        line_slots = {
            row.get("id"): index + 1 for index, row in enumerate(legacy_lines)
        }
        active_line_count = sum(bool(row.get("active", True)) for row in legacy_lines)
        tables["production_settings"] = [{
            "id": 1,
            "line_count": max(active_line_count, 1),
            "updated_at": payload["created_at"],
        }]
        selected_capabilities: dict[int, dict[str, Any]] = {}
        for row in tables.get("production_capabilities", []):
            row["line_id"] = None
            product_id = row.get("product_id")
            current = selected_capabilities.get(product_id)
            row_capacity = float(row.get("nominal_daily_capacity", 0))
            current_capacity = (
                float(current.get("nominal_daily_capacity", 0))
                if current else -1
            )
            if current is None or row_capacity > current_capacity:
                selected_capabilities[product_id] = row
        tables["production_capabilities"] = list(selected_capabilities.values())
        for row in tables.get("production_runs", []):
            row.setdefault("line_slot", line_slots.get(row.get("line_id"), 1))
            row["line_id"] = None
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version in {1, 2, 3, 4, 5, 6, 7}:
        for row in tables.get("production_runs", []):
            row.setdefault("schedule_locked", False)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version in {1, 2, 3, 4, 5, 6, 7, 8}:
        for row in tables.get("production_settings", []):
            row.setdefault("schedule_auto_snap", True)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version in {1, 2, 3, 4, 5, 6, 7, 8, 9}:
        legacy_capacity: dict[int, int] = {}
        for row in tables.get("production_capabilities", []):
            if not row.get("active", True):
                continue
            product_id = int(row.get("product_id", 0) or 0)
            capacity = int(row.get("nominal_daily_capacity", 0) or 0)
            legacy_capacity[product_id] = max(
                legacy_capacity.get(product_id, 0),
                capacity,
            )
        for row in tables.get("inventory_items", []):
            if row.get("kind") != "PRODUCT":
                continue
            row["daily_capacity"] = int(
                row.get("daily_capacity", 0)
                or legacy_capacity.get(int(row.get("id", 0) or 0), 0)
            )
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 10:
        for row in tables.get("sales_order_items", []):
            row.setdefault("shipped_quantity", 0)
        for row in tables.get("stock_transactions", []):
            row.setdefault("related_production_run_id", None)
            row.setdefault("order_no_snapshot", None)
            row.setdefault("counterparty_name_snapshot", None)
            row.setdefault("counterparty_phone_snapshot", None)
            row.setdefault("counterparty_address_snapshot", None)
            row.setdefault("operator_snapshot", None)
        for row in tables.get("stock_transaction_items", []):
            row.setdefault("sku_snapshot", None)
            row.setdefault("name_snapshot", None)
            row.setdefault("spec_snapshot", None)
            row.setdefault("unit_snapshot", None)
            row.setdefault("unit_price_snapshot", None)
            row.setdefault("line_total_snapshot", None)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 11:
        for row in tables.get("inventory_items", []):
            row.setdefault("semi_finished_qty", 0)
            row.setdefault("processing_qty", 0)
            row.setdefault("requires_external_processing", False)
            row.setdefault("external_process_name", "")
        for row in tables.get("sales_order_items", []):
            row.setdefault("returned_quantity", 0)
            row.setdefault("pipeline_quantity", 0)
        tables.setdefault("order_returns", [])
        tables.setdefault("external_processing_batches", [])
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 12:
        for row in tables.get("production_runs", []):
            row.setdefault("scrap_quantity", 0)
            row.setdefault("termination_reason", "")
            row.setdefault("terminated_at", None)
            row.setdefault("workflow_version", 1)
        tables.setdefault("production_material_reservations", [])
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 13:
        for row in tables.get("stock_transactions", []):
            row.setdefault("status", "POSTED")
            row.setdefault("reversal_of_transaction_id", None)
            row.setdefault("reversed_by_transaction_id", None)
        for row in tables.get("stock_transaction_items", []):
            row.setdefault("inventory_bucket", "FINISHED")
            row.setdefault("affects_primary_stock", True)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 14:
        for row in tables.get("inventory_items", []):
            row.setdefault("default_external_lead_days", 0)
        for row in tables.get("order_returns", []):
            row.setdefault("resolution", "REFUND")
        for row in tables.get("external_processing_batches", []):
            row.setdefault("expected_return_at", None)
        tables.setdefault("purchase_commitments", [])
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 15:
        for row in tables.get("production_settings", []):
            row.setdefault("working_weekdays", "1,2,3,4,5")
        tables.setdefault("production_calendar_exceptions", [])
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 16:
        for row in tables.get("operation_logs", []):
            row.setdefault("business_summary", "")
        tables.setdefault("receivables", [])
        tables.setdefault("payments", [])
        tables.setdefault("payment_allocations", [])
        tables.setdefault("users", [])
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 17:
        for row in tables.get("sales_order_items", []):
            row.setdefault("replacement_pending_quantity", 0)
        for row in tables.get("receivables", []):
            row.setdefault("related_stock_transaction_id", None)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 18:
        tables.setdefault("order_shipment_allocations", [])
        for row in tables.get("sales_order_items", []):
            row.setdefault("replacement_shipped_quantity", 0)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 19:
        for row in tables.get("external_processing_batches", []):
            row.setdefault("processing_cost", 0)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 20:
        tables.setdefault("customer_credits", [])
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
    if schema_version <= 21:
        for row in tables.get("order_returns", []):
            row.setdefault("refund_unit_price_snapshot", None)
            row.setdefault("return_unit_cost_snapshot", None)
        payload["schema_version"] = BACKUP_SCHEMA_VERSION
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

    try:
        from .planning import recalculate_production_plan
        from .services import rebalance_product_reservations
        from sqlalchemy import select
        product_ids = set(db.scalars(select(InventoryItem.id).where(InventoryItem.kind == "PRODUCT")).all())
        rebalance_product_reservations(db, product_ids)
        recalculate_production_plan(db)
        db.commit()
    except Exception:
        db.rollback()

    restored = _metadata(path, payload)
    return {
        "ok": True,
        "restored_backup": restored,
        "safety_backup": safety_backup,
        "restored_records": restored["total_records"],
    }
