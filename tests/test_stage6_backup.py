from datetime import date
import json
from pathlib import Path
import sys
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.backup as backup_module
import app.main as main_module
import app.planning as planning_module
from app.backup import BackupRestoreError, create_backup_archive, restore_backup_archive
from app.database import Base
from app.models import (
    CustomerCredit,
    InventoryItem,
    OperationLog,
    OrderReturn,
    OrderShipmentAllocation,
    SalesOrder,
    SalesOrderItem,
    StockReservation,
    StockTransaction,
    User,
)
from app.auth import create_access_token
from app.database import get_db
from app.services import hash_password


def database() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    return Session(engine)


def backup_path(metadata: dict) -> Path:
    return backup_module.BACKUP_DIRECTORY / metadata["filename"]


def add_active_order(db: Session) -> tuple[InventoryItem, SalesOrderItem]:
    product = InventoryItem(
        sku="P-BACKUP",
        name="备份产品",
        kind="PRODUCT",
        stock_qty=5,
        daily_capacity=10,
        mold_count=1,
        sale_price=20,
    )
    order = SalesOrder(
        order_no="SO-BACKUP",
        customer_name="备份客户",
        status="CONFIRMED",
        order_date=date(2026, 8, 23),
        required_date=date(2026, 8, 25),
        total_amount=200,
    )
    line = SalesOrderItem(
        product=product,
        quantity=10,
        reserved_quantity=99,
        pipeline_quantity=99,
        production_required_quantity=99,
        reference_price=20,
        unit_price=20,
        line_total=200,
    )
    order.items = [line]
    db.add(order)
    db.commit()
    return product, line


def rewrite_as_schema21(path: Path) -> None:
    with ZipFile(path, "r") as archive:
        payload = json.loads(archive.read("backup.json").decode("utf-8"))
    payload["schema_version"] = 21
    for row in payload["tables"]["order_returns"]:
        row.pop("refund_unit_price_snapshot", None)
        row.pop("return_unit_cost_snapshot", None)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("backup.json", json.dumps(payload, ensure_ascii=False))


def test_restore_rebuilds_derived_state_and_creates_pre_restore_backup(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_module, "BACKUP_DIRECTORY", tmp_path)
    with database() as db:
        product, line = add_active_order(db)
        source = create_backup_archive(db)
        source_path = backup_path(source)

        product.stock_qty = 77
        line.reserved_quantity = 0
        db.commit()

        result = restore_backup_archive(db, source_path)

        assert result["ok"] is True
        assert result["safety_backup"]["backup_type"] == "PRE_RESTORE"
        assert result["safety_backup"]["source_backup"] == source["filename"]
        restored_product = db.scalar(select(InventoryItem).where(InventoryItem.sku == "P-BACKUP"))
        restored_line = db.scalar(select(SalesOrderItem))
        reservation = db.scalar(select(StockReservation).where(StockReservation.order_item_id == restored_line.id))
        assert restored_product.stock_qty == 5
        assert restored_line.reserved_quantity == 5
        assert restored_line.production_required_quantity == 5
        assert reservation.quantity == restored_line.reserved_quantity

        safety_path = tmp_path / result["safety_backup"]["filename"]
        with ZipFile(safety_path, "r") as archive:
            safety_payload = json.loads(archive.read("backup.json").decode("utf-8"))
        safety_product = next(row for row in safety_payload["tables"]["inventory_items"] if row["sku"] == "P-BACKUP")
        assert safety_product["stock_qty"] == 77


def test_restore_rebuild_failure_never_reports_success_and_rolls_back(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_module, "BACKUP_DIRECTORY", tmp_path)
    with database() as db:
        product, _ = add_active_order(db)
        source_path = backup_path(create_backup_archive(db))
        product.stock_qty = 77
        db.commit()

        def fail_rebuild(*_args, **_kwargs):
            raise RuntimeError("controlled planner failure")

        monkeypatch.setattr(planning_module, "recalculate_production_plan", fail_rebuild)
        with pytest.raises(BackupRestoreError) as caught:
            restore_backup_archive(db, source_path)

        assert caught.value.stage == "RESTORE_REBUILD_VALIDATE"
        assert "未将本次操作视为恢复成功" in str(caught.value)
        assert caught.value.safety_backup["backup_type"] == "PRE_RESTORE"
        assert db.scalar(select(InventoryItem.stock_qty).where(InventoryItem.sku == "P-BACKUP")) == 77


def test_restore_api_returns_500_and_audits_rebuild_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_module, "BACKUP_DIRECTORY", tmp_path)
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def override_get_db():
        with factory() as session:
            yield session

    main_module.app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    try:
        with factory() as db:
            add_active_order(db)
            admin = User(
                username="backup-admin",
                password_hash=hash_password("backup-password"),
                display_name="备份管理员",
                role="ADMIN",
            )
            db.add(admin)
            db.commit()
            db.refresh(admin)
            filename = create_backup_archive(db)["filename"]
            token = create_access_token(admin.id, admin.username, admin.role, admin.display_name)

        def fail_rebuild(*_args, **_kwargs):
            raise RuntimeError("controlled planner failure")

        monkeypatch.setattr(planning_module, "recalculate_production_plan", fail_rebuild)
        response = TestClient(main_module.app).post(
            f"/api/backups/{filename}/restore",
            headers={"Authorization": f"Bearer {token}"},
            json={"confirm_filename": filename},
        )

        assert response.status_code == 500
        assert "未将本次操作视为恢复成功" in response.json()["detail"]
        with factory() as db:
            log = db.scalar(select(OperationLog).where(
                OperationLog.action == "恢复数据备份",
                OperationLog.status == "FAILED",
            ))
            assert log is not None
            assert filename in log.target
            assert "RESTORE_REBUILD_VALIDATE" in log.detail
            assert "password" not in log.detail.lower()
    finally:
        main_module.app.dependency_overrides.pop(get_db, None)


def test_schema21_restore_defaults_return_snapshots_to_none(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_module, "BACKUP_DIRECTORY", tmp_path)
    with database() as db:
        product = InventoryItem(sku="P21", name="旧产品", kind="PRODUCT", daily_capacity=1, mold_count=1)
        order = SalesOrder(
            order_no="SO21",
            customer_name="旧客户",
            status="DRAFT",
            order_date=date(2026, 8, 23),
            required_date=date(2026, 8, 23),
        )
        line = SalesOrderItem(product=product, quantity=1, reference_price=8, unit_price=8, line_total=8)
        order.items = [line]
        db.add(order)
        db.flush()
        db.add(OrderReturn(
            return_no="RT21",
            order=order,
            order_item=line,
            product=product,
            quantity=1,
            refund_unit_price_snapshot=8,
            return_unit_cost_snapshot=3,
        ))
        db.commit()
        source_path = backup_path(create_backup_archive(db))
        rewrite_as_schema21(source_path)

        result = restore_backup_archive(db, source_path)

        assert result["ok"] is True
        restored = db.scalar(select(OrderReturn))
        assert restored.refund_unit_price_snapshot is None
        assert restored.return_unit_cost_snapshot is None


def test_schema22_roundtrip_preserves_stage5_financial_and_shipment_data(tmp_path, monkeypatch):
    monkeypatch.setattr(backup_module, "BACKUP_DIRECTORY", tmp_path)
    with database() as db:
        product = InventoryItem(sku="P22", name="新产品", kind="PRODUCT", daily_capacity=1, mold_count=1)
        order = SalesOrder(
            order_no="SO22",
            customer_name="新客户",
            status="DRAFT",
            order_date=date(2026, 8, 23),
            required_date=date(2026, 8, 23),
        )
        line = SalesOrderItem(product=product, quantity=5, reference_price=80, unit_price=80, line_total=400)
        order.items = [line]
        transaction = StockTransaction(
            transaction_no="TX22",
            transaction_type="SALE_OUT",
            related_order=order,
        )
        db.add_all([order, transaction])
        db.flush()
        allocation = OrderShipmentAllocation(
            order_item=line,
            transaction=transaction,
            fulfillment_type="ORIGINAL",
            quantity=5,
            unit_price_snapshot=80,
        )
        returned = OrderReturn(
            return_no="RT22",
            order=order,
            order_item=line,
            product=product,
            quantity=5,
            refund_unit_price_snapshot=80,
            return_unit_cost_snapshot=32,
        )
        db.add_all([allocation, returned])
        db.flush()
        db.add(CustomerCredit(
            credit_no="CR22",
            order=order,
            order_return=returned,
            customer_name="新客户",
            amount=400,
            kind="REFUND_DUE",
        ))
        db.commit()
        source_path = backup_path(create_backup_archive(db))

        returned.refund_unit_price_snapshot = 1
        returned.return_unit_cost_snapshot = 1
        allocation.quantity = 1
        credit = db.scalar(select(CustomerCredit))
        credit.amount = 1
        db.commit()

        result = restore_backup_archive(db, source_path)

        assert result["ok"] is True
        restored_return = db.scalar(select(OrderReturn))
        restored_allocation = db.scalar(select(OrderShipmentAllocation))
        restored_credit = db.scalar(select(CustomerCredit))
        assert restored_return.refund_unit_price_snapshot == 80
        assert restored_return.return_unit_cost_snapshot == 32
        assert restored_allocation.quantity == 5
        assert restored_allocation.unit_price_snapshot == 80
        assert restored_credit.amount == 400
        assert restored_credit.order_return_id == restored_return.id
