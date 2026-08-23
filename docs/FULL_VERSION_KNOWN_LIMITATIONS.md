# Full V1 已知技术边界

本文记录 Full V1 的真实技术边界，供部署、运维和后续版本设计使用，不代表未来功能承诺。

## 1. Production planning

当前生产计划由 `recalculate_production_plan()` 全量重算，不是增量 planner。Full V1 先以 Stage 7 的真实 MySQL benchmark 判断目标规模是否够用；未得到性能证据前不为此重写算法。

## 2. Production resource model

`production_lines`、`molds`、`product_molds`、`production_capabilities` 仍为旧数据和旧备份兼容保留。当前核心调度主要使用 `ProductionSetting.line_count`、`InventoryItem.mold_count` 和 `InventoryItem.daily_capacity`，不能宣称 legacy resource model 已正式启用。

## 3. MES boundary

ERP 管理生产需求、计划、ETA、开工、最终合格产出、报废和终止。它不提供工序级采集、OEE、设备实时状态、PLC、工位或实时 MES 能力。

## 4. Inventory bucket limitation

FINISHED / primary stock 的流水和只读对账较完整。`semi_finished_qty`、`processing_qty` 与 `sample_stock_qty` 仍不能全部仅凭库存流水独立重建；样品流水明确不影响 primary stock。系统不提供完整的多 bucket 总账。

无任何历史主库存流水的旧物料在对账时以当前 `stock_qty` 作为基准并明确标注。正式新库应从零库存建档，并通过 OPENING 或正式出入库流水形成期初事实。

## 5. Costing

库存采用移动平均成本。Production 成本使用领料时的 unit-cost snapshot。系统不执行历史 COGS 重放；采购入库在后续业务已经消耗其库存时，危险冲销会被拒绝。

## 6. External processing costing

`ExternalProcessingBatch` 使用送出时 PROCESS_OUT 的成本 snapshot，并叠加录入的加工费。同一半成品池若混有不同成本来源，当前没有 lot-level costing，只能按移动平均/近似口径管理。

## 7. Returns

Stage 5.7 之后的新退货锁定 `refund_unit_price_snapshot` 与 `return_unit_cost_snapshot`，以剩余物理价值池保证交错出库/退货的价值守恒。Stage 5.7 之前的历史退货 snapshot 为 NULL，系统不会动态重算或假装恢复精确历史价值。正式业务库建议从 migration head 新建。

## 8. SALE_OUT reversal after returns

一旦 `SalesOrderItem` 已发生任何 `OrderReturn`，Full V1 禁止直接冲销该订单行的历史 SALE_OUT，以保护已经锁定的退货价值 snapshot。退货冲销、贷项冲销和价值池重建如有需要，必须作为独立版本设计。

## 9. Finance

当前只提供 `Receivable`、`Payment`、`PaymentAllocation` 和 `CustomerCredit`。它不是完整复式记账、总账、应付账款、税务或银行对账系统。

## 10. Multi warehouse

Full V1 不支持多仓、库位或多工厂，也没有跨仓调拨语义。

## 11. Lot / Serial

Full V1 不支持批次追踪、序列号追踪或精确的退货 lot 成本匹配。销售退货因此采用剩余物理价值池方法。

## 12. Backup old versions

当前 backup schema version 为 22。恢复流程会为旧 schema 补齐兼容字段和空表，但不能凭空恢复旧退货 snapshot。任何 restore、derived rebuild 或关键不变量校验失败都不会返回成功；PRE_RESTORE 安全备份会保留供管理员处理。

## 13. Concurrency

出库、退货、生产、支付核销、CustomerCredit settle 等关键路径已在 MySQL 使用 `SELECT ... FOR UPDATE`。SQLite 单元测试不能证明真实并发正确；Stage 7 必须在真实 MySQL 上用两个独立 Session 验证竞争路径。

## 14. Security

系统使用 JWT、数据库角色实时检查和默认关闭的 break-glass emergency admin。生产模式强制要求显式 `ERP_JWT_SECRET`。`/api/events` 当前公开，以兼容 EventSource 不能携带 Authorization header 的限制，但事件只发送 `id`、`source`、`occurred_at`，不包含业务数据。
