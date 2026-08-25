"""Lite V1 representative planner performance guard."""

from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import (
    InventoryItem,
    ProductBomItem,
    ProductionSetting,
    SalesOrder,
    SalesOrderItem,
)
from app.planning import recalculate_production_plan


NOW = datetime(2026, 8, 20, 8, 0)


def test_lite_representative_planner_reports_runtime():
    """Report runtime for 120 products + 500 orders, including 20 active orders."""
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add(ProductionSetting(id=1, line_count=16))
        material = InventoryItem(
            sku="LITE-MATERIAL",
            name="Lite shared material",
            kind="PART",
            stock_qty=1_000_000,
            cost_price=1,
        )
        db.add(material)
        db.flush()

        products = []
        for index in range(120):
            product = InventoryItem(
                sku=f"LITE-P-{index:03d}",
                name=f"Lite product {index:03d}",
                kind="PRODUCT",
                stock_qty=0,
                daily_capacity=100,
                mold_count=2,
            )
            db.add(product)
            db.flush()
            db.add(ProductBomItem(product_id=product.id, part_id=material.id, quantity=1))
            products.append(product)

        for index in range(500):
            active = index < 20
            product = products[index % len(products)]
            quantity = 100 if active else 10
            order = SalesOrder(
                order_no=f"LITE-SO-{index:04d}",
                customer_name=f"Customer {index:04d}",
                status="CONFIRMED" if active else "FULFILLED",
                order_date=NOW.date(),
                required_date=NOW.date() + timedelta(days=5 + index % 5),
                total_amount=quantity,
                items=[SalesOrderItem(
                    product_id=product.id,
                    quantity=quantity,
                    shipped_quantity=0 if active else quantity,
                    reference_price=1,
                    unit_price=1,
                    line_total=quantity,
                )],
            )
            db.add(order)
        db.commit()

        started = perf_counter()
        result = recalculate_production_plan(db, NOW)
        elapsed = perf_counter() - started

        print(f"LITE_PLANNER_SECONDS={elapsed:.3f}")
        assert result["active_order_count"] == 20
        assert result["created_run_count"] > 0
