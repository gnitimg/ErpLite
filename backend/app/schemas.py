from datetime import date

from pydantic import BaseModel, Field, field_validator


class LoginPayload(BaseModel):
    username: str
    password: str
    code: str


class PartPayload(BaseModel):
    sku: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=120)
    unit: str = Field(default="件", max_length=20)
    spec: str = Field(default="", max_length=200)
    cost_price: float = Field(default=0, ge=0)
    min_stock: float = Field(default=0, ge=0)

    @field_validator("sku", "name")
    @classmethod
    def strip_required(cls, value: str):
        value = value.strip()
        if not value:
            raise ValueError("不能为空")
        return value


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
    min_stock: float = Field(default=0, ge=0)
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


class OrderLinePayload(BaseModel):
    product_id: int
    quantity: float = Field(gt=0)
    unit_price: float = Field(ge=0)


class OrderPayload(BaseModel):
    customer_name: str = Field(min_length=1, max_length=120)
    customer_phone: str = Field(default="", max_length=40)
    customer_address: str = Field(default="", max_length=255)
    order_date: date = Field(default_factory=date.today)
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
