from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class LoginPayload(BaseModel):
    username: str
    password: str
    code: str = ""


class BackupRestorePayload(BaseModel):
    confirm_filename: str = Field(min_length=1, max_length=255)


class PartPayload(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(default="件", max_length=20)
    spec: str = Field(default="", max_length=200)
    cost_price: float = Field(default=0, ge=0)
    min_stock: float = Field(default=0, ge=0)
    supply_mode: Literal["STOCK", "BUY_TO_ORDER"] = "STOCK"

    @field_validator("sku", "name")
    @classmethod
    def strip_required(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


class SamplePayload(BaseModel):
    stock_qty: int = Field(ge=0)


class BomLinePayload(BaseModel):
    part_id: int
    quantity: float = Field(gt=0)


class ProductPayload(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(default="件", max_length=20)
    spec: str = Field(default="", max_length=200)
    cost_price: float = Field(default=0, ge=0)
    sale_price: float = Field(default=0, ge=0)
    min_stock: int = Field(default=0, ge=0)
    mold_count: int = Field(default=1, ge=1)
    daily_capacity: int = Field(default=0, ge=0)
    requires_external_processing: bool = False
    external_process_name: str = Field(default="", max_length=120)
    default_external_lead_days: int = Field(default=0, ge=0)
    components: list[BomLinePayload] = Field(default_factory=list)

    @field_validator("sku", "name")
    @classmethod
    def strip_required(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value

    @field_validator("components")
    @classmethod
    def unique_parts(cls, value: list[BomLinePayload]):
        ids = [line.part_id for line in value]
        if len(ids) != len(set(ids)):
            raise ValueError("同一个零件不能重复添加")
        return value

    @field_validator("external_process_name")
    @classmethod
    def external_process_required(cls, value: str, info):
        value = value.strip()
        if info.data.get("requires_external_processing") and not value:
            raise ValueError("启用外协加工时必须填写工序名称")
        return value


class StockPayload(BaseModel):
    item_id: int
    quantity: float = Field(gt=0)
    unit_cost: float = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=500)
    consume_bom: bool = False
    production_run_id: int | None = None


class StockDocumentLinePayload(BaseModel):
    item_id: int
    quantity: float = Field(gt=0)
    unit_price: float = Field(default=0, ge=0)


class StockDocumentPayload(BaseModel):
    direction: Literal["INBOUND", "OUTBOUND"]
    counterparty_name: str = Field(default="", max_length=120)
    counterparty_phone: str = Field(default="", max_length=40)
    counterparty_address: str = Field(default="", max_length=255)
    occurred_date: date = Field(default_factory=date.today)
    operator: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=500)
    items: list[StockDocumentLinePayload] = Field(min_length=1)

    @field_validator("items")
    @classmethod
    def unique_document_items(cls, value: list[StockDocumentLinePayload]):
        ids = [line.item_id for line in value]
        if len(ids) != len(set(ids)):
            raise ValueError("同一张单据不能重复添加相同物料")
        return value

class OrderStockPayload(BaseModel):
    notes: str = Field(default="", max_length=500)


class OrderLinePayload(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    unit_price: float = Field(ge=0)


class OrderPayload(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    customer_phone: str = Field(default="", max_length=40)
    customer_address: str = Field(default="", max_length=255)
    order_date: date = Field(default_factory=date.today)
    required_date: date | None = None
    notes: str = Field(default="", max_length=500)
    items: list[OrderLinePayload] = Field(min_length=1)

    @field_validator("customer_name")
    @classmethod
    def strip_customer(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("客户名称不能为空")
        return value

    @field_validator("items")
    @classmethod
    def unique_products(cls, value: list[OrderLinePayload]):
        ids = [line.product_id for line in value]
        if len(ids) != len(set(ids)):
            raise ValueError("同一个产品不能重复添加")
        return value

    @field_validator("required_date")
    @classmethod
    def required_not_before_order(cls, value: date | None, info):
        order_date = info.data.get("order_date")
        if value and order_date and value < order_date:
            raise ValueError("要求交期不能早于订单日期")
        return value


class ProductionSettingsPayload(BaseModel):
    line_count: int = Field(default=1, ge=1, le=100)
    schedule_auto_snap: bool = True
    working_weekdays: str = Field(default="1,2,3,4,5", max_length=20)


class PrintSettingsPayload(BaseModel):
    paper_preset: Literal[
        "A4_LANDSCAPE",
        "A4_PORTRAIT",
        "A5_LANDSCAPE",
        "A5_PORTRAIT",
        "CONTINUOUS_HALF",
        "CONTINUOUS_THIRD",
        "CUSTOM",
    ] = "A4_LANDSCAPE"
    width_mm: float = Field(default=297, ge=50, le=500)
    height_mm: float = Field(default=210, ge=50, le=500)


class ProductionRunStatusPayload(BaseModel):
    status: Literal["RUNNING", "CANCELLED", "TERMINATED"]
    qualified_quantity: int | None = Field(default=None, ge=0)
    scrap_quantity: int = Field(default=0, ge=0)
    termination_reason: str = Field(default="", max_length=500)


class ManualProductionRunPayload(BaseModel):
    product_id: int
    planned_quantity: int = Field(gt=0)
    line_slot: int = Field(default=1, ge=1, le=100)
    planned_start_date: date = Field(default_factory=date.today)
    notes: str = Field(default="", max_length=500)


class ProductionCompletionPayload(BaseModel):
    qualified_quantity: int = Field(gt=0)
    scrap_quantity: int = Field(default=0, ge=0)
    completion_date: date = Field(default_factory=date.today)
    notes: str = Field(default="", max_length=500)


class OrderShipmentLinePayload(BaseModel):
    order_item_id: int
    quantity: int = Field(gt=0)
    unit_price: float | None = Field(default=None, ge=0)


class OrderShipmentPayload(BaseModel):
    items: list[OrderShipmentLinePayload] = Field(min_length=1)
    counterparty_name: str = Field(default="", max_length=120)
    counterparty_phone: str = Field(default="", max_length=40)
    counterparty_address: str = Field(default="", max_length=255)
    occurred_date: date = Field(default_factory=date.today)
    operator: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=500)

    @field_validator("items")
    @classmethod
    def unique_order_items(cls, value: list[OrderShipmentLinePayload]):
        ids = [line.order_item_id for line in value]
        if len(ids) != len(set(ids)):
            raise ValueError("同一订单产品不能重复出库")
        return value


class OrderReturnLinePayload(BaseModel):
    order_item_id: int
    quantity: int = Field(gt=0)
    restock: bool = True


class OrderReturnPayload(BaseModel):
    items: list[OrderReturnLinePayload] = Field(min_length=1)
    resolution: Literal["REFUND", "REPLACE"] = "REFUND"
    occurred_date: date = Field(default_factory=date.today)
    notes: str = Field(default="", max_length=500)

    @field_validator("items")
    @classmethod
    def unique_return_items(cls, value: list[OrderReturnLinePayload]):
        ids = [line.order_item_id for line in value]
        if len(ids) != len(set(ids)):
            raise ValueError("同一次退货不能重复选择同一订单产品")
        return value


class ExternalProcessingSendPayload(BaseModel):
    product_id: int
    quantity: int = Field(gt=0)
    supplier: str = Field(default="", max_length=120)
    occurred_date: date = Field(default_factory=date.today)
    lead_days: int = Field(default=0, ge=0)
    expected_return_at: datetime | None = None
    processing_cost: float = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=500)


class ExternalProcessingReturnPayload(BaseModel):
    quantity: int = Field(gt=0)
    occurred_date: date = Field(default_factory=date.today)
    notes: str = Field(default="", max_length=500)


class ProductionRunSchedulePayload(BaseModel):
    line_slot: int = Field(ge=1, le=100)
    planned_start_at: datetime


class OrderCancelPayload(BaseModel):
    disposition: Literal["cancel_runs", "convert_to_replenishment", "keep_runs"] | None = None


class PurchaseCommitmentPayload(BaseModel):
    part_id: int
    quantity: float = Field(gt=0)
    expected_arrival_date: date
    supplier_text: str = Field(default="", max_length=120)
    notes: str = Field(default="", max_length=500)


class PurchaseCommitmentStatusPayload(BaseModel):
    status: Literal["PLANNED", "ARRIVED", "CANCELLED"]


class CalendarExceptionPayload(BaseModel):
    exception_date: date
    is_working_day: bool = False
    note: str = Field(default="", max_length=200)


class PaymentPayload(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    amount: float = Field(gt=0)
    payment_date: date = Field(default_factory=date.today)
    method: Literal["CASH", "TRANSFER", "OTHER"] = "TRANSFER"
    notes: str = Field(default="", max_length=500)


class PaymentAllocationPayload(BaseModel):
    receivable_id: int
    amount: float = Field(gt=0)


class CreditSettlementPayload(BaseModel):
    settled_amount: float = Field(gt=0)
    notes: str = Field(default="", max_length=500)


class UserPayload(BaseModel):
    username: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=120)
    display_name: str = Field(default="", max_length=120)
    role: Literal["ADMIN", "OPERATOR", "VIEWER"] = "OPERATOR"

    @field_validator("username")
    @classmethod
    def strip_username(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("用户名不能为空")
        return value


class UserUpdatePayload(BaseModel):
    display_name: str = Field(default="", max_length=120)
    role: Literal["ADMIN", "OPERATOR", "VIEWER"] = "OPERATOR"
    active: bool = True
    password: str | None = Field(default=None, min_length=1, max_length=120)


class StockReconciliationLinePayload(BaseModel):
    item_id: int
    physical_count: float = Field(ge=0)


class StockReconciliationPayload(BaseModel):
    items: list[StockReconciliationLinePayload] = Field(min_length=1)
    notes: str = Field(default="", max_length=500)

    @field_validator("items")
    @classmethod
    def unique_reconciliation_items(cls, value: list[StockReconciliationLinePayload]):
        ids = [line.item_id for line in value]
        if len(ids) != len(set(ids)):
            raise ValueError("对账中不能重复选择同一物料")
        return value
