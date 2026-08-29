from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
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
    cost_price: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    sale_price: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    min_stock: Mapped[float] = mapped_column(Float, default=0)
    daily_capacity: Mapped[int] = mapped_column(Integer, default=0)
    mold_count: Mapped[int] = mapped_column(Integer, default=0)
    stock_qty: Mapped[float] = mapped_column(Float, default=0)
    semi_finished_qty: Mapped[int] = mapped_column(Integer, default=0)
    processing_qty: Mapped[int] = mapped_column(Integer, default=0)
    requires_external_processing: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    external_process_name: Mapped[str] = mapped_column(String(120), default="")
    default_external_lead_days: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
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
    reference_price: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False))
    line_total: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False))
    production_required_quantity: Mapped[float] = mapped_column(Float, default=0)
    replacement_pending_quantity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    replacement_shipped_quantity: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
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
    resolution: Mapped[str] = mapped_column(String(20), default="REFUND", server_default="REFUND")
    transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    notes: Mapped[str] = mapped_column(Text, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    # 5.7：退货发生时锁定的单价/成本快照，后续出库不能改写历史退货价值。
    refund_unit_price_snapshot: Mapped[float | None] = mapped_column(
        Numeric(18, 2, asdecimal=False), nullable=True, server_default=None
    )
    return_unit_cost_snapshot: Mapped[float | None] = mapped_column(
        Numeric(18, 2, asdecimal=False), nullable=True, server_default=None
    )

    order: Mapped[SalesOrder] = relationship()
    order_item: Mapped[SalesOrderItem] = relationship()
    product: Mapped[InventoryItem] = relationship()
    transaction: Mapped["StockTransaction | None"] = relationship()

    __table_args__ = (Index("ix_order_returns_order_time", "order_id", "occurred_at"),)


class OrderShipmentAllocation(Base):
    """出库履约分配：记录每笔销售出库对订单行的完成来源（原单 ORIGINAL / 换货补发 REPLACEMENT）。

    冲销 SALE_OUT 时据此精确恢复 shipped_quantity 或 replacement_pending_quantity；
    换货已补发数量也从这里推导（已冲销流水的分配不计入）。
    """

    __tablename__ = "order_shipment_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_item_id: Mapped[int] = mapped_column(
        ForeignKey("sales_order_items.id", ondelete="CASCADE"), index=True
    )
    stock_transaction_id: Mapped[int] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="CASCADE"), index=True
    )
    fulfillment_type: Mapped[str] = mapped_column(String(20), default="ORIGINAL", server_default="ORIGINAL")
    quantity: Mapped[int] = mapped_column(Integer)
    unit_price_snapshot: Mapped[float | None] = mapped_column(Numeric(18, 2, asdecimal=False), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    order_item: Mapped[SalesOrderItem] = relationship()
    transaction: Mapped["StockTransaction"] = relationship(back_populates="shipment_allocations")


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
    working_weekdays: Mapped[str] = mapped_column(String(20), default="1,2,3,4,5", server_default="1,2,3,4,5")
    print_paper_preset: Mapped[str] = mapped_column(String(30), default="A4_LANDSCAPE")
    print_width_mm: Mapped[float] = mapped_column(Float, default=297)
    print_height_mm: Mapped[float] = mapped_column(Float, default=210)
    # 单据页眉：none 不显示 / name 仅厂名 / logo 仅标志 / both 厂名+标志
    print_header_mode: Mapped[str] = mapped_column(String(10), default="none", server_default="none")
    print_company_name: Mapped[str] = mapped_column(String(100), default="", server_default="")
    print_logo: Mapped[str] = mapped_column(Text, default="", server_default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class DocumentNumberRule(Base):
    """可配置的业务单号规则；每个 document_type 独立、事务内递增。"""

    __tablename__ = "document_number_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    document_type: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    prefix: Mapped[str] = mapped_column(String(12), default="")
    next_number: Mapped[int] = mapped_column(Integer, default=1)
    digits: Mapped[int] = mapped_column(Integer, default=6)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )


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
    termination_reason: Mapped[str] = mapped_column(Text, default="")
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
    status: Mapped[str] = mapped_column(String(20), default="POSTED", server_default="POSTED", index=True)
    reversal_of_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="SET NULL"), nullable=True
    )
    reversed_by_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    lines: Mapped[list["StockTransactionItem"]] = relationship(cascade="all, delete-orphan", back_populates="transaction")
    shipment_allocations: Mapped[list["OrderShipmentAllocation"]] = relationship(
        cascade="all, delete-orphan", back_populates="transaction"
    )
    related_order: Mapped[SalesOrder | None] = relationship()
    related_production_run: Mapped[ProductionRun | None] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "reversal_of_transaction_id",
            name="uq_stock_transactions_reversal_of",
        ),
        Index(
            "ix_stock_transactions_reversed_by",
            "reversed_by_transaction_id",
        ),
    )


class StockTransactionItem(Base):
    __tablename__ = "stock_transaction_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey("stock_transactions.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True)
    quantity_change: Mapped[float] = mapped_column(Float)
    unit_cost: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    sku_snapshot: Mapped[str | None] = mapped_column(String(50), nullable=True)
    name_snapshot: Mapped[str | None] = mapped_column(String(120), nullable=True)
    spec_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)
    unit_snapshot: Mapped[str | None] = mapped_column(String(20), nullable=True)
    unit_price_snapshot: Mapped[float | None] = mapped_column(Numeric(18, 2, asdecimal=False), nullable=True)
    line_total_snapshot: Mapped[float | None] = mapped_column(Numeric(18, 2, asdecimal=False), nullable=True)
    inventory_bucket: Mapped[str] = mapped_column(String(20), default="FINISHED", server_default="FINISHED")
    affects_primary_stock: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

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
    expected_return_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    returned_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 本批次外协加工总费用（人工输入），回厂时按比例摊入成品成本。
    processing_cost: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0, server_default="0")
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
    business_summary: Mapped[str] = mapped_column(String(500), default="", server_default="")
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


class PurchaseCommitment(Base):
    """轻量采购预计到货，用于 ETA 物料可用时间计算。"""

    __tablename__ = "purchase_commitments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    part_id: Mapped[int] = mapped_column(
        ForeignKey("inventory_items.id", ondelete="RESTRICT"), index=True
    )
    quantity: Mapped[float] = mapped_column(Float)
    expected_arrival_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    status: Mapped[str] = mapped_column(String(20), default="PLANNED", index=True)
    supplier_text: Mapped[str] = mapped_column(String(120), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    part: Mapped[InventoryItem] = relationship()


class ProductionCalendarException(Base):
    """生产日历例外日期，覆盖默认工作日设置。"""

    __tablename__ = "production_calendar_exceptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    exception_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    is_working_day: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(200), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class Receivable(Base):
    """应收账款记录，出库时自动生成。"""

    __tablename__ = "receivables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    receivable_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    related_stock_transaction_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_transactions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(120), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    settled_amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    order: Mapped[SalesOrder | None] = relationship()
    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        cascade="all, delete-orphan", back_populates="receivable"
    )

    __table_args__ = (Index("ix_receivables_status_created", "status", "created_at"),)


class Payment(Base):
    """付款记录，可分配核销到多笔应收。"""

    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    customer_name: Mapped[str] = mapped_column(String(120), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    allocated_amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    payment_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    method: Mapped[str] = mapped_column(String(20), default="TRANSFER")
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    allocations: Mapped[list["PaymentAllocation"]] = relationship(
        cascade="all, delete-orphan", back_populates="payment"
    )

    __table_args__ = (Index("ix_payments_customer_date", "customer_name", "payment_date"),)


class PaymentAllocation(Base):
    """付款到应收的核销分配记录。"""

    __tablename__ = "payment_allocations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), index=True
    )
    receivable_id: Mapped[int] = mapped_column(
        ForeignKey("receivables.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)

    payment: Mapped[Payment] = relationship(back_populates="allocations")
    receivable: Mapped[Receivable] = relationship(back_populates="allocations")

    __table_args__ = (
        UniqueConstraint("payment_id", "receivable_id", name="uq_payment_receivable"),
    )


class CustomerCredit(Base):
    """客户贷项 / 应退款。

    退款退货（REFUND）产生：
    - OFFSET_RECEIVABLE：应收尚未收齐，贷项直接冲减应收余额，status=SETTLED。
    - REFUND_DUE：应收已收齐（或冲减后仍有剩余），剩余部分形成客户应退现金，
      status=OPEN；管理员登记退款完成后置为 SETTLED。

    换货退货（REPLACE）不产生任何贷项。
    原应收 amount 永不修改，历史完整保留。
    """

    __tablename__ = "customer_credits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credit_no: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("sales_orders.id", ondelete="SET NULL"), nullable=True, index=True
    )
    order_return_id: Mapped[int | None] = mapped_column(
        ForeignKey("order_returns.id", ondelete="SET NULL"), nullable=True, index=True
    )
    receivable_id: Mapped[int | None] = mapped_column(
        ForeignKey("receivables.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(120), index=True)
    amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    settled_amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0)
    kind: Mapped[str] = mapped_column(
        String(20), default="REFUND_DUE", server_default="REFUND_DUE", index=True
    )
    status: Mapped[str] = mapped_column(String(20), default="OPEN", index=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    order: Mapped[SalesOrder | None] = relationship()
    order_return: Mapped[OrderReturn | None] = relationship()
    receivable: Mapped[Receivable | None] = relationship()

    __table_args__ = (Index("ix_credits_status_created", "status", "created_at"),)


class User(Base):
    """系统用户，支持角色权限和密码验证。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(200), default="")
    display_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20), default="OPERATOR", index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    # 首次登录强制改密标志：初始默认 admin 用弱口令 12345678 时为 True，
    # 改密成功后清除；登录时也会按明文密码强度动态复核。
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    navigation_config: Mapped[str] = mapped_column(String(4000), default="", server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
