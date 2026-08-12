from datetime import date
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


class StockPayload(BaseModel):
    item_id: int
    quantity: float = Field(gt=0)
    unit_cost: float = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=500)
    consume_bom: bool = True


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
