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
    daily_capacity: Mapped[int] = mapped_column(Integer, default=0)
    mold_count: Mapped[int] = mapped_column(Integer, default=0)
    stock_qty: Mapped[float] = mapped_column(Float, default=0)
    semi_finished_qty: Mapped[int] = mapped_column(Integer, default=0)
    processing_qty: Mapped[int] = mapped_column(Integer, default=0)
    requires_external_processing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    external_process_name: Mapped[str] = mapped_column(String(120), default="")
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
    quantity: Mapped[int] = mapped_column(Integer)
    shipped_quantity: Mapped[int] = mapped_column(Integer, default=0)
    returned_quantity: Mapped[int] = mapped_column(Integer, default=0)
    reserved_quantity: Mapped[int] = mapped_column(Integer, default=0)
    pipeline_quantity: Mapped[int] = mapped_column(Integer, default=0)
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


class OrderReturn(Base):
    __tablename__ = "order_returns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    return_no: Mapped[str] = mapped_column(String(50), index=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("sales_orders.id", ondelete="CASCADE"), index=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("sales_order_items.id", ondelete="RESTRICT"),
        index=True,
    )
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    quantity: Mapped[int] = mapped_column(Integer)
    restocked: Mapped[bool] = mapped_column(Boolean, default=True)
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    order: Mapped[SalesOrder] = relationship()
    order_item: Mapped[SalesOrderItem] = relationship()
    product: Mapped[InventoryItem] = relationship()
    transaction: Mapped["StockTransaction | None"] = relationship()

    __table_args__ = (Index("ix_order_returns_order_time", "order_id", "occurred_at"),)


class ProductionLine(Base):
    """旧版产线档案，仅为历史批次和旧备份兼容保留。"""

    __tablename__ = "production_lines"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ProductionSetting(Base):
    """全局系统设置；当前系统固定只使用 id=1 的单例记录。"""

    __tablename__ = "production_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    line_count: Mapped[int] = mapped_column(Integer, default=1)
    schedule_auto_snap: Mapped[bool] = mapped_column(Boolean, default=True)
    print_paper_preset: Mapped[str] = mapped_column(String(30), default="A4_LANDSCAPE")
    print_width_mm: Mapped[float] = mapped_column(Float, default=297)
    print_height_mm: Mapped[float] = mapped_column(Float, default=210)
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
    mold_id: Mapped[int] = mapped_column(
        ForeignKey("molds.id", ondelete="RESTRICT"), index=True
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)

    product: Mapped[InventoryItem] = relationship()
    mold: Mapped[Mold] = relationship()

    __table_args__ = (UniqueConstraint("product_id", "mold_id", name="uq_product_mold"),)


class ProductionCapability(Base):
    __tablename__ = "production_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="CASCADE"), index=True)
    line_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_lines.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    mold_id: Mapped[int | None] = mapped_column(
        ForeignKey("molds.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    nominal_daily_capacity: Mapped[int] = mapped_column(Integer)
    safety_factor: Mapped[float] = mapped_column(Float, default=0.85)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    product: Mapped[InventoryItem] = relationship()
    line: Mapped[ProductionLine | None] = relationship()
    mold: Mapped[Mold | None] = relationship()

    __table_args__ = (
        UniqueConstraint("product_id", "line_id", "mold_id", name="uq_production_capability"),
        Index("ix_capability_product_active", "product_id", "active"),
        Index("ix_capability_product_line", "product_id", "line_id"),
    )


class ProductionRun(Base):
    __tablename__ = "production_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    line_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_lines.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    line_slot: Mapped[int] = mapped_column(Integer, default=1)
    mold_id: Mapped[int | None] = mapped_column(
        ForeignKey("molds.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    mold_slot: Mapped[int] = mapped_column(Integer, default=1)
    planned_quantity: Mapped[int] = mapped_column(Integer)
    produced_quantity: Mapped[int] = mapped_column(Integer, default=0)
    planned_start_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    effective_daily_capacity: Mapped[float] = mapped_column(Float)
    schedule_locked: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    source_type: Mapped[str] = mapped_column(
        String(20), default="ORDER", server_default="ORDER", index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)
    scrap_quantity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    termination_reason: Mapped[str] = mapped_column(Text, default="", server_default="")
    terminated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    workflow_version: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    product: Mapped[InventoryItem] = relationship()
    line: Mapped[ProductionLine | None] = relationship()
    mold: Mapped[Mold | None] = relationship()
    allocations: Mapped[list["ProductionAllocation"]] = relationship(
        cascade="all, delete-orphan", back_populates="production_run"
    )
    material_reservations: Mapped[list["ProductionMaterialReservation"]] = relationship(
        cascade="all, delete-orphan", back_populates="production_run",
    )

    __table_args__ = (
        Index("ix_runs_line_status_start", "line_id", "status", "planned_start_at"),
        Index("ix_runs_line_slot_status_start", "line_slot", "status", "planned_start_at"),
        Index("ix_runs_mold_status_start", "mold_id", "status", "planned_start_at"),
        Index(
            "ix_runs_product_mold_slot_status",
            "product_id",
            "mold_slot",
            "status",
        ),
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
    related_production_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("production_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_no_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    counterparty_name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    counterparty_phone_snapshot: Mapped[str | None] = mapped_column(String(40), nullable=True)
    counterparty_address_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)
    operator_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lines: Mapped[list["StockTransactionItem"]] = relationship(cascade="all, delete-orphan", back_populates="transaction")
    related_order: Mapped[SalesOrder | None] = relationship()
    related_production_run: Mapped[ProductionRun | None] = relationship()


class StockTransactionItem(Base):
    __tablename__ = "stock_transaction_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("stock_transactions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    quantity_change: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Float, default=0)
    sku_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    spec_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_price_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)
    line_total_snapshot: Mapped[float | None] = mapped_column(Float, nullable=True)

    transaction: Mapped[StockTransaction] = relationship(back_populates="lines")
    item: Mapped[InventoryItem] = relationship()


class ExternalProcessingBatch(Base):
    __tablename__ = "external_processing_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    process_name_snapshot: Mapped[str] = mapped_column(String(120))
    supplier: Mapped[str] = mapped_column(String(120), default="")
    quantity: Mapped[int] = mapped_column(Integer)
    returned_quantity: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="SENT", index=True)
    outbound_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="RESTRICT"), index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    product: Mapped[InventoryItem] = relationship()
    outbound_transaction: Mapped[StockTransaction] = relationship(foreign_keys=[outbound_transaction_id])

    __table_args__ = (Index("ix_external_batches_status_sent", "status", "sent_at"),)


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


class ProductionMaterialReservation(Base):
    """生产批次的物料占用预留，用于确定性的物料齐套检查。

    按 planned_start_at、run_id 排序依次从真实零件库存分配，
    避免多个 PLANNED 批次同时看到同一批库存可用。
    """

    __tablename__ = "production_material_reservations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    production_run_id: Mapped[int] = mapped_column(
        ForeignKey("production_runs.id", ondelete="CASCADE"), index=True
    )
    part_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    production_run: Mapped[ProductionRun] = relationship(back_populates="material_reservations")
    part: Mapped[InventoryItem] = relationship()

    __table_args__ = (
        UniqueConstraint("production_run_id", "part_id", name="uq_run_part_reservation"),
        Index("ix_reservation_part_status", "part_id", "status"),
    )
