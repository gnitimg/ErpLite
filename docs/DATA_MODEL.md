# 数据模型与业务约束

## 先验证的核心问题

这个精简 ERP 最容易出错的问题不是页面，而是“BOM、入库、出库和客单是否会让库存出现两个真相”。本项目采用以下答案：

1. 零件和产品都是库存物料，统一保存在 `inventory_items`。
2. 产品组成由 `product_bom_items` 保存；每行表示生产 1 单位产品所需的零件数量。
3. `inventory_items.stock_qty` 是快速读取的实时结存，但任何修改必须和 `stock_transactions`、`stock_transaction_items` 流水在同一数据库事务中完成。
4. 产品生产入库是一笔复合流水：成品为正数，BOM 零件按“入库数量 × 单台用量”为负数；任何零件不足时整笔失败。
5. 客单确认后按要求交期预留成品库存；点击“出库”时统一校验并扣减已预留成品，成功后客单进入 `FULFILLED`。
6. 当前版本禁止负库存。已产生业务历史的物料采用停用而非物理删除。
7. 同一笔库存业务涉及的全部物料按 ID 固定顺序加行锁，结存和流水在同一事务中写入。

## 表结构

### `inventory_items`

统一物料主数据。`kind` 为 `PART` 或 `PRODUCT`；包含编码、名称、规格、单位、成本、售价、安全库存、实时结存和启用状态。

### `product_bom_items`

产品 BOM。外键 `product_id`、`part_id` 指向统一物料表，联合唯一；`quantity` 为单台用量。

### `sales_orders` / `sales_order_items`

客户订单头与产品明细。状态流转为 `DRAFT → CONFIRMED / WAITING_MATERIALS → READY_TO_SHIP → FULFILLED`，未完结状态可转为 `CANCELLED`。明细保存参考价、本单成交价和预留数量。

### `stock_transactions` / `stock_transaction_items`

库存业务流水头与明细。明细使用带符号的 `quantity_change`：正数入库，负数出库。一笔期初盘点可包含多种物料；一笔生产入库可以同时记录成品增加与多个零件减少。普通结存可由全部非样品流水汇总复核。

## 后续扩展位置

- 多仓库：增加 `warehouses`，将 `stock_qty` 拆到 `stock_balances(item_id, warehouse_id)`。
- 批次/序列号：在流水明细增加批次或序列号维度。
- 采购管理：新增供应商、采购单，入库流水关联采购单。
- 预占库存：为已确认客单增加 reservation 表，区分账面库存和可用库存。
- 多实例与云数据库：调整 `.env` 中的 MySQL 主机、端口与账号即可，业务 API 不变。
