from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class InventoryItem(Base):
    __tablename__ = "inventory_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sku: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)  # PART / PRODUCT
    unit: Mapped[str] = mapped_column(String(20), default="件")
    spec: Mapped[str] = mapped_column(String(200), default="")
    cost_price: Mapped[float] = mapped_column(Float, default=0)
    sale_price: Mapped[float] = mapped_column(Float, default=0)
    min_stock: Mapped[float] = mapped_column(Float, default=0)
    daily_capacity: Mapped[float] = mapped_column(Float, default=0)  # 兼容旧库；ETA 不读取此字段
    stock_qty: Mapped[float] = mapped_column(Float, default=0)
    sample_stock_qty: Mapped[int] = mapped_column(Integer, default=300)
    supply_mode: Mapped[str] = mapped_column(String(20), default="STOCK")  # STOCK / BUY_TO_ORDER（仅零件）
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    bom_components: Mapped[list["ProductBomItem"]] = relationship(
        foreign_keys="ProductBomItem.product_id", cascade="all, delete-orphan", back_populates="product"
    )

    __table_args__ = (Index("ix_items_kind_active", "kind", "active"),)


class ProductBomItem(Base):
    __tablename__ = "product_bom_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True)
    part_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[float] = mapped_column(Float)

    product: Mapped[InventoryItem] = relationship(foreign_keys=[product_id], back_populates="bom_components")
    part: Mapped[InventoryItem] = relationship(foreign_keys=[part_id])

    __table_args__ = (UniqueConstraint("product_id", "part_id", name="uq_product_bom_part"),)


class SalesOrder(Base):
    __tablename__ = "sales_orders"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(120), index=True)
    customer_phone: Mapped[str] = mapped_column(String(40), default="")
    customer_address: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    order_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    required_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0)
    estimated_completion_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    eta_calculated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eta_reliable: Mapped[bool] = mapped_column(Boolean, default=False)
    eta_note: Mapped[str] = mapped_column(String(500), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    items: Mapped[list["SalesOrderItem"]] = relationship(cascade="all, delete-orphan", back_populates="order")

    __table_args__ = (Index("ix_orders_status_required", "status", "required_date"),)


class SalesOrderItem(Base):
    __tablename__ = "sales_order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[float] = mapped_column(Float)
    reserved_quantity: Mapped[float] = mapped_column(Float, default=0)
    reference_price: Mapped[float] = mapped_column(Float, default=0)
    unit_price: Mapped[float] = mapped_column(Float)
    line_total: Mapped[float] = mapped_column(Float)
    production_required_quantity: Mapped[float] = mapped_column(Float, default=0)
    estimated_completion_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    eta_reliable: Mapped[bool] = mapped_column(Boolean, default=False)
    eta_note: Mapped[str] = mapped_column(String(500), default="")

    order: Mapped[SalesOrder] = relationship(back_populates="items")
    product: Mapped[InventoryItem] = relationship()


class StockReservation(Base):
    """订单成品预留的权威记录；SalesOrderItem.reserved_quantity 仅保留为兼容缓存。"""

    __tablename__ = "stock_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("sales_order_items.id", ondelete="CASCADE"), unique=True, index=True
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    order_item: Mapped[SalesOrderItem] = relationship()
    product: Mapped[InventoryItem] = relationship()

    __table_args__ = (Index("ix_reservations_product_status", "product_id", "status"),)


class ProductionLine(Base):
    __tablename__ = "production_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class Mold(Base):
    __tablename__ = "molds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProductMold(Base):
    __tablename__ = "product_molds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True)
    mold_id: Mapped[int] = mapped_column(ForeignKey("molds.id", ondelete="RESTRICT"), index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[InventoryItem] = relationship()
    mold: Mapped[Mold] = relationship()

    __table_args__ = (UniqueConstraint("product_id", "mold_id", name="uq_product_mold"),)


class ProductionCapability(Base):
    __tablename__ = "production_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id", ondelete="RESTRICT"), index=True)
    mold_id: Mapped[int] = mapped_column(ForeignKey("molds.id", ondelete="RESTRICT"), index=True)
    nominal_daily_capacity: Mapped[int] = mapped_column(Integer)
    safety_factor: Mapped[float] = mapped_column(Float, default=0.85)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    product: Mapped[InventoryItem] = relationship()
    line: Mapped[ProductionLine] = relationship()
    mold: Mapped[Mold] = relationship()

    __table_args__ = (
        UniqueConstraint("product_id", "line_id", "mold_id", name="uq_production_capability"),
        Index("ix_capability_product_active", "product_id", "active"),
    )


class ProductionRun(Base):
    __tablename__ = "production_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("production_lines.id", ondelete="RESTRICT"), index=True)
    mold_id: Mapped[int] = mapped_column(ForeignKey("molds.id", ondelete="RESTRICT"), index=True)
    planned_quantity: Mapped[int] = mapped_column(Integer)
    produced_quantity: Mapped[int] = mapped_column(Integer, default=0)
    planned_start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_daily_capacity: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    product: Mapped[InventoryItem] = relationship()
    line: Mapped[ProductionLine] = relationship()
    mold: Mapped[Mold] = relationship()
    allocations: Mapped[list["ProductionAllocation"]] = relationship(
        cascade="all, delete-orphan", back_populates="production_run"
    )

    __table_args__ = (
        Index("ix_runs_line_status_start", "line_id", "status", "planned_start_at"),
        Index("ix_runs_mold_status_start", "mold_id", "status", "planned_start_at"),
    )


class ProductionAllocation(Base):
    __tablename__ = "production_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_run_id: Mapped[int] = mapped_column(
        ForeignKey("production_runs.id", ondelete="CASCADE"), index=True
    )
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("sales_order_items.id", ondelete="CASCADE"), index=True
    )
    quantity: Mapped[int] = mapped_column(Integer)
    sequence: Mapped[int] = mapped_column(Integer)
    estimated_completion_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    production_run: Mapped[ProductionRun] = relationship(back_populates="allocations")
    order_item: Mapped[SalesOrderItem] = relationship()

    __table_args__ = (
        UniqueConstraint("production_run_id", "order_item_id", name="uq_run_order_item"),
        Index("ix_allocations_order_sequence", "order_item_id", "sequence"),
    )


class StockTransaction(Base):
    __tablename__ = "stock_transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    transaction_type: Mapped[str] = mapped_column(String(30), index=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    related_order_id: Mapped[int | None] = mapped_column(ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lines: Mapped[list["StockTransactionItem"]] = relationship(cascade="all, delete-orphan", back_populates="transaction")
    related_order: Mapped[SalesOrder | None] = relationship()


class StockTransactionItem(Base):
    __tablename__ = "stock_transaction_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("stock_transactions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    quantity_change: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)

    transaction: Mapped[StockTransaction] = relationship(back_populates="lines")
    item: Mapped[InventoryItem] = relationship()


class OperationLog(Base):
    __tablename__ = "operation_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(120), default="", index=True)
    action: Mapped[str] = mapped_column(String(60), default="", index=True)
    target: Mapped[str] = mapped_column(String(255), default="")
    method: Mapped[str] = mapped_column(String(10), default="")
    path: Mapped[str] = mapped_column(String(255), default="", index=True)
    ip_address: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(20), default="SUCCESS", index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
