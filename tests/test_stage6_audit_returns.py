from datetime import date, datetime
from pathlib import Path
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import operation_action, order_return_dict
from app.models import InventoryItem, OrderReturn, SalesOrder, SalesOrderItem


def return_row(
    resolution: str = "REFUND",
    refund_price: float | None = 80,
    return_cost: float | None = 32,
) -> OrderReturn:
    product = InventoryItem(id=1, sku="P-RETURN", name="退货产品", kind="PRODUCT", unit="件")
    order = SalesOrder(
        id=1,
        order_no="SO-RETURN",
        customer_name="客户",
        order_date=date(2026, 8, 23),
        required_date=date(2026, 8, 23),
    )
    line = SalesOrderItem(
        id=1,
        order=order,
        product=product,
        quantity=5,
        unit_price=80,
        line_total=400,
    )
    return OrderReturn(
        id=1,
        return_no="RT-RETURN",
        order=order,
        order_item=line,
        product=product,
        quantity=5,
        restocked=True,
        resolution=resolution,
        refund_unit_price_snapshot=refund_price,
        return_unit_cost_snapshot=return_cost,
        notes="",
        occurred_at=datetime(2026, 8, 23, 10, 0),
    )


def test_refund_return_api_exposes_locked_snapshot_totals():
    result = order_return_dict(return_row())

    assert result["refund_unit_price_snapshot"] == 80
    assert result["refund_total"] == 400
    assert result["return_unit_cost_snapshot"] == 32
    assert result["return_cost_total"] == 160


def test_legacy_null_snapshots_remain_null_without_recalculation():
    result = order_return_dict(return_row(refund_price=None, return_cost=None))

    assert result["refund_unit_price_snapshot"] is None
    assert result["refund_total"] is None
    assert result["return_unit_cost_snapshot"] is None
    assert result["return_cost_total"] is None


def test_replace_return_keeps_audit_fields_but_is_explicitly_typed():
    result = order_return_dict(return_row(resolution="REPLACE"))

    assert result["resolution"] == "REPLACE"
    assert result["refund_total"] == 400


def test_key_business_paths_have_traceable_actions():
    expected = {
        ("/api/orders/1/confirm", "POST"): "确认客单",
        ("/api/orders/1/cancel", "POST"): "取消客单",
        ("/api/orders/1/ship", "POST"): "客单出库",
        ("/api/orders/1/returns", "POST"): "客单退货",
        ("/api/stock/transactions/1/reverse", "POST"): "库存流水冲销",
        ("/api/production/runs/1/complete", "POST"): "生产完工",
        ("/api/production/runs/1/status", "PUT"): "生产开工/终止",
        ("/api/finance/payments", "POST"): "收款创建",
        ("/api/finance/payments/1/allocate", "POST"): "应收核销",
        ("/api/finance/credits/1/settle", "POST"): "客户退款登记",
        ("/api/backups/example/restore", "POST"): "恢复数据备份",
    }
    assert {
        key: operation_action(*key)
        for key in expected
    } == expected
