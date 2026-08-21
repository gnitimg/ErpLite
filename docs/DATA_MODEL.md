# 数据模型与业务约束

## 先验证的核心问题

这个精简 ERP 最容易出错的问题不是页面，而是“BOM、入库、出库和客单是否会让库存出现两个真相”。本项目采用以下答案：

1. 零件和产品都是库存物料，统一保存在 `inventory_items`。
2. 产品组成由 `product_bom_items` 保存；每行表示生产 1 单位产品所需的零件数量。
3. `inventory_items.stock_qty` 是快速读取的实时结存，但任何修改必须和 `stock_transactions`、`stock_transaction_items` 流水在同一数据库事务中完成。
4. 产品生产审核在一个数据库事务中生成两笔流水：BOM 零件自动形成生产耗用出库，合格成品形成生产入库；任何零件不足时两笔都失败。
5. 客单确认后按要求交期创建成品预留；预留基数始终是 `quantity - shipped_quantity`。订单允许多次出库，全部出完才进入 `FULFILLED`。
6. 当前版本禁止负库存。已产生业务历史的物料采用停用而非物理删除。
7. 同一笔库存业务涉及的全部物料按 ID 固定顺序加行锁，结存和流水在同一事务中写入。

## 表结构

### `inventory_items`

统一物料主数据。`kind` 为 `PART` 或 `PRODUCT`；包含编码、名称、规格、单位、成本、售价、安全库存、实时结存和启用状态。产品额外直接保存模具数量 `mold_count` 和整数单机日产量 `daily_capacity`。

### `product_bom_items`

产品 BOM。外键 `product_id`、`part_id` 指向统一物料表，联合唯一；`quantity` 为单台用量。

### `sales_orders` / `sales_order_items`

客户订单头与产品明细。明细保存整数 `quantity`、`shipped_quantity`，剩余数量由两者相减。状态流转为 `DRAFT → CONFIRMED / WAITING_MATERIALS / READY_TO_SHIP → PARTIALLY_SHIPPED → FULFILLED`；第一次出库后订单业务内容冻结。订单和明细缓存 ETA、可靠性和原因，可由生产计划重建。

### `stock_reservations`

已确认客单剩余未出库部分的成品库存预留。`inventory_items.stock_qty` 继续表示物理结存，预留不直接扣减它。每条客单明细最多一条权威预留，且 `reservation.quantity <= quantity - shipped_quantity`。

### 产品模具数量 / `production_settings`

`inventory_items.mold_count` 直接保存产品拥有的模具套数，产品表单中维护，零件为 0。排产时为每套模具建立产品内的逻辑 `mold_slot`，同一模具位同一时刻只能被一个生产批次占用。`production_settings` 是单例全局设置：`line_count` 表示系统允许同时运行的生产任务数，`schedule_auto_snap` 控制排产图拖动时是否吸附到日期刻度或相邻批次边界。系统据此生成逻辑生产位，不维护产线编号、名称或独立档案。`molds`、`product_molds` 与 `production_lines` 仅为旧版数据和备份兼容保留。

### 产品单机日产量

`inventory_items.daily_capacity` 是排产使用的唯一产能数据源，直接在产品目录维护，不再引入安全系数。时间块时长为 `计划数量 ÷ 单机日产量`，实际并行数不超过全局 `line_count` 和产品 `mold_count` 中的较小值。`production_capabilities` 仅为旧版数据和备份兼容保留，新业务不再写入或读取。

### `production_runs`

按产品合并后的连续生产段，保存产品、逻辑 `line_slot`、`mold_slot`、计划/实际数量、计划/实际时间和执行状态。`schedule_locked` 表示批次是否已由用户在订单排产时间轴中确认；人工确认批次在自动重算时作为固定时间轴保留，未确认的建议批次可以重建。它不直接归属于客单；生产位与产品模具位的占用时间轴由人工排期、运行中的批次和模拟计划共同形成。`line_id` 仅为兼容旧批次保留，新记录固定为空。

### `production_allocations`

把 `production_runs` 的产量分配到 `sales_order_items`。同一连续批次可以服务多个客单，`sequence` 表示累计产出优先满足顺序，明细 ETA 是累计供给达到该订单所需数量的时刻，而不是统一使用批次结束时间。

### `stock_transactions` / `stock_transaction_items`

库存业务流水头与明细。明细使用带符号的 `quantity_change`：正数入库，负数出库。生产审核按实际合格数量生成 `PRODUCTION_OUT` 零件耗用单和 `ASSEMBLY_IN` 产品入库单，两者通过 `related_production_run_id` 关联同一批次；只有销售出库通过 `related_order_id` 关联订单。

单据头保存订单号、客户名称、电话、地址和经办人快照；单据行保存 SKU、名称、规格、单位以及可选成交价快照。旧流水快照允许为空，读取时回退当前主数据；新流水始终写快照，因此历史单据不会被后续主数据改名影响。

## 聚合需求规则

- 成品库存先按要求交期分配，订单生产缺口为 `remaining - reserved`。
- 全部订单的生产缺口按 `product_id` 合并；有效 `ProductionAllocation` 是已排产覆盖量，未覆盖部分才创建新批次。
- 全部产品需求展开 BOM 后按 `part_id` 汇总，再减一次当前零件库存，得到“待购买”。缺料只影响 ETA 可靠性，不阻断排产。
- `ProductionRun` 正常状态从 `PLANNED` 直接完工为 `COMPLETED`；历史 `RUNNING` 继续兼容并允许直接完工。

## 后续扩展位置

- 多仓库：增加 `warehouses`，将 `stock_qty` 拆到 `stock_balances(item_id, warehouse_id)`。
- 批次/序列号：在流水明细增加批次或序列号维度。
- 采购管理：新增供应商、采购单，入库流水关联采购单。
- 智能排产：在保留现有可解释启发式的基础上，可后续增加插单阈值、换模时间和 OR-Tools 优化器。
- 多实例与云数据库：调整 `.env` 中的 MySQL 主机、端口与账号即可，业务 API 不变。
