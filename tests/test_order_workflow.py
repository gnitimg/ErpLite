from datetime import date, timedelta
from pathlib import Path
import sys

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.database import Base
from app.models import InventoryItem, ProductBomItem, SalesOrder, SalesOrderItem
from app.services import (
    load_order,
    order_workflow_dict,
    prepare_order_stock,
    rebalance_product_reservations,
    release_order_reservations,
)


def make_order(db: Session, product: InventoryItem, order_no: str, required_date: date, quantity: float) -> SalesOrder:
    order = SalesOrder(
        order_no=order_no,
        customer_name=order_no,
        status="CONFIRMED",
        order_date=date.today(),
        required_date=required_date,
        total_amount=quantity * product.sale_price,
    )
    order.items = [SalesOrderItem(
        product_id=product.id,
        quantity=quantity,
        reference_price=product.sale_price,
        unit_price=product.sale_price - 10,
        line_total=quantity * (product.sale_price - 10),
    )]
    db.add(order)
    db.flush()
    return order


def main() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        part = InventoryItem(sku="PART", name="按单采购件", kind="PART", supply_mode="BUY_TO_ORDER", stock_qty=2)
        product = InventoryItem(sku="PRODUCT", name="产品", kind="PRODUCT", sale_price=100, stock_qty=1)
        db.add_all([part, product])
        db.flush()
        db.add(ProductBomItem(product_id=product.id, part_id=part.id, quantity=1))
        later = make_order(db, product, "SO-LATER", date.today() + timedelta(days=10), 1)
        earlier = make_order(db, product, "SO-EARLIER", date.today() + timedelta(days=2), 1)
        db.commit()

        rebalance_product_reservations(db, {product.id})
        db.commit()
        earlier = load_order(db, earlier.id)
        later = load_order(db, later.id)
        assert earlier.items[0].reserved_quantity == 1
        assert later.items[0].reserved_quantity == 0
        assert earlier.status == "READY_TO_SHIP"
        assert later.status == "WAITING_MATERIALS"
        assert order_workflow_dict(db, later)["product_lines"][0]["priority_rank"] == 2

        product.stock_qty = 0
        earlier.items[0].reserved_quantity = 0
        later.items[0].reserved_quantity = 0
        earlier.status = "WAITING_MATERIALS"
        later.status = "WAITING_MATERIALS"
        db.commit()
        waiting_result = prepare_order_stock(db, load_order(db, later.id))
        assert waiting_result["workflow"]["next_action"] == "WAIT_PRIORITY"
        assert product.stock_qty == 0

        release_order_reservations(db, earlier)
        earlier.status = "CANCELLED"
        product.stock_qty = 1
        rebalance_product_reservations(db, {product.id})
        db.commit()
        later = load_order(db, later.id)
        assert later.items[0].reserved_quantity == 1
        assert later.status == "READY_TO_SHIP"

        product.stock_qty = 0
        later.items[0].reserved_quantity = 0
        later.status = "CONFIRMED"
        db.commit()
        result = prepare_order_stock(db, load_order(db, later.id))
        assert result["order"]["status"] == "READY_TO_SHIP"
        assert product.stock_qty == 1
        assert part.stock_qty == 1
        assert result["order"]["items"][0]["discount_rate"] == 90

    print("order workflow: ok")


if __name__ == "__main__":
    main()
