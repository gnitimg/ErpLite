# 数据模型与业务约束

## 先验证的核心问题

这个精简 ERP 最容易出错的问题不是页面，而是“BOM、入库、出库和客单是否会让库存出现两个真相”。本项目采用以下答案：

1. 零件和产品都是库存物料，统一保存在 `inventory_items`。
2. 产品组成由 `product_bom_items` 保存；每行表示生产 1 单位产品所需的零件数量。
3. `inventory_items.stock_qty` 是快速读取的实时结存，但任何修改必须和 `stock_transactions`、`stock_transaction_items` 流水在同一数据库事务中完成。
4. 产品生产入库是一笔复合流水：成品为正数，BOM 零件按“入库数量 × 单台用量”为负数；任何零件不足时整笔失败。
5. 客单确认后按要求交期创建 `stock_reservations` 成品预留；点击“出库”时统一校验并扣减已预留成品，成功后客单进入 `FULFILLED`。
6. 当前版本禁止负库存。已产生业务历史的物料采用停用而非物理删除。
7. 同一笔库存业务涉及的全部物料按 ID 固定顺序加行锁，结存和流水在同一事务中写入。

## 表结构

### `inventory_items`

统一物料主数据。`kind` 为 `PART` 或 `PRODUCT`；包含编码、名称、规格、单位、成本、售价、安全库存、实时结存和启用状态。

### `product_bom_items`

产品 BOM。外键 `product_id`、`part_id` 指向统一物料表，联合唯一；`quantity` 为单台用量。

### `sales_orders` / `sales_order_items`

客户订单头与产品明细。状态流转为 `DRAFT → CONFIRMED / WAITING_MATERIALS → READY_TO_SHIP → FULFILLED`，未完结状态可转为 `CANCELLED`。订单和明细缓存预计完成时间、计算时间、可靠性和原因；缓存可由生产计划重建。

### `stock_reservations`

已确认客单的成品库存预留。`inventory_items.stock_qty` 继续表示物理结存，预留不直接扣减它。可承诺库存等于物理结存减去其他有效预留；每条客单明细最多一条权威预留记录。

### 产品模具数量 / `production_settings`

`inventory_items.mold_count` 直接保存产品拥有的模具套数，产品表单中维护，零件为 0。排产时为每套模具建立产品内的逻辑 `mold_slot`，同一模具位同一时刻只能被一个生产批次占用。`production_settings` 是单例全局设置：`line_count` 表示系统允许同时运行的生产任务数，`schedule_auto_snap` 控制排产图拖动时是否吸附到日期刻度或相邻批次边界。系统据此生成逻辑生产位，不维护产线编号、名称或独立档案。`molds`、`product_molds` 与 `production_lines` 仅为旧版数据和备份兼容保留。

### `production_capabilities`

每个产品维护一条用户填写的单日单机产量和安全系数。ETA 使用 `nominal_daily_capacity × safety_factor`，时间块时长为 `计划数量 ÷ 单机有效日产`；产品表遗留的 `daily_capacity` 不参与排产。实际并行数不超过全局 `line_count` 和该产品 `mold_count` 中的较小值。`line_id` 仅为兼容旧数据保留，新记录固定为空。

### `production_runs`

按产品合并后的连续生产段，保存产品、逻辑 `line_slot`、`mold_slot`、计划/实际数量、计划/实际时间和执行状态。`schedule_locked` 表示批次是否已由用户在订单排产时间轴中确认；人工确认批次在自动重算时作为固定时间轴保留，未确认的建议批次可以重建。它不直接归属于客单；生产位与产品模具位的占用时间轴由人工排期、运行中的批次和模拟计划共同形成。`line_id` 仅为兼容旧批次保留，新记录固定为空。

### `production_allocations`

把 `production_runs` 的产量分配到 `sales_order_items`。同一连续批次可以服务多个客单，`sequence` 表示累计产出优先满足顺序，明细 ETA 是累计供给达到该订单所需数量的时刻，而不是统一使用批次结束时间。

### `stock_transactions` / `stock_transaction_items`

库存业务流水头与明细。明细使用带符号的 `quantity_change`：正数入库，负数出库。一笔期初盘点可包含多种物料；一笔生产入库可以同时记录成品增加与多个零件减少。普通结存可由全部非样品流水汇总复核。

## 后续扩展位置

- 多仓库：增加 `warehouses`，将 `stock_qty` 拆到 `stock_balances(item_id, warehouse_id)`。
- 批次/序列号：在流水明细增加批次或序列号维度。
- 采购管理：新增供应商、采购单，入库流水关联采购单。
- 智能排产：在保留现有可解释启发式的基础上，可后续增加插单阈值、换模时间和 OR-Tools 优化器。
- 多实例与云数据库：调整 `.env` 中的 MySQL 主机、端口与账号即可，业务 API 不变。
