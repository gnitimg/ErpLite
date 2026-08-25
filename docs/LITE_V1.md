# ErpLite Lite V1

Full Base SHA: `7994d9448bb02561dc26ba84595e89837f34770e`

Branch: `feature`

Lite V1 keeps the Full V1 data model and transactional invariants while reducing the daily workflow to seven navigation concepts: 总览、订单、生产排期、库存、采购、财务、设置。

## Navigation

- 总览：经营待办、交期风险、待生产、待采购、应收未收。
- 订单：客户订单和销售出库单。
- 生产排期：自动/人工排期与完工登记。
- 库存：原料、成品、出入库、盘点、单据和流水。
- 采购：采购缺口、采购预计到货和到货登记。
- 财务：应收、收款、退款与贷项。
- 设置：产品/BOM、原料、产能、日历、打印、备份、用户和操作日志。

旧 Full URL 继续存在于隐藏路由中，避免破坏历史书签。Samples、External Processing 和 Full/MES 式入口不出现在 Lite 主导航。

## Dashboard

总览使用老板和生产负责人的经营语言展示：进行中订单、七天内到期、延期/ETA 风险、待生产、待采购原料和应收未收。近期订单表直接比较要求交期、预计可交时间与风险原因，不展示库存流水 ID 等内部技术字段。

## Orders

订单保留草稿、确认、取消、多产品、部分出库、订单快照与退换货。确认顺序不变：先用成品库存预留，再仅对剩余缺口创建生产需求。订单明细集中展示订单数量、库存满足、待生产、已出库、剩余和预计可交时间。

## Production

Lite 正常流程为 `PLANNED -> COMPLETED`。用户登记实际合格数、报废数和完成日期；系统在同一事务内完成 BOM 倒冲、成本快照、成品入库、订单预留再平衡与计划/ETA 重算。原料不足返回 HTTP 409，库存不会变负。

## Planner / ETA

自动排期、人工拖动、排期锁、生产合批、客户分配、line count、mold count、工作日历、采购承诺材料时间线和理论 ETA 全部保留。订单 ETA 仍为订单行 ETA 的最大值；材料不足不会删除排期，只会降低 ETA 可靠性。

## Inventory

Lite 页面区分原料和成品，重点展示 SKU、名称、当前库存、订单预留、可用库存、安全库存、成本以及生产/采购缺口。入库、出库、盘点、库存流水、库存审计和历史单据继续保留。

## Purchase

采购缺口页合并展示原料当前库存、生产需求、采购缺口、已登记采购和最近预计到货日期。采购预计到货仍使用 `PurchaseCommitment`，`PLANNED` 进入材料时间线，`ARRIVED`/`CANCELLED` 保持终态。

## Finance

财务页面使用应收、已收、未收、退款/贷项等业务语言。底层继续使用 `Receivable`、`Payment`、`PaymentAllocation` 和 `CustomerCredit`，没有简化或绕过金额锁、贷项锁及价值守恒。

## Returns

退款退货、换货和是否回库继续支持。界面隐藏退货成本等内部字段，但历史成交价、出库成本和退货成本快照仍保存在后端；存在退货后禁止直接冲销相关 `SALE_OUT` 的规则不变。

## Documents

销售出库单、普通入库单、普通出库单和生产入库记录继续保留。单据继续依赖 snapshot，后续修改客户、产品或价格不会改写历史事实。

## Security

`ADMIN`、`OPERATOR`、`VIEWER`、用户停用、last-admin 保护、数据库当前角色检查、操作日志和首次登录强制改密保持不变。Lite V1 未扩展认证模型。

## Backup

创建备份、备份列表、恢复、版本检查、路径安全、恢复前安全快照和恢复失败 rollback 全部保留。

## Hidden Full Features

- Samples 主入口
- External Processing 主入口和产品页配置
- 开工、终止、生产领料及物料 reservation 详情
- 半成品、外协在途等非 Lite 库存栏
- 操作日志的 HTTP path/IP/technical detail（仅展开时显示）

## Legacy Compatibility

Full schema 是 Lite schema 的超集。没有删除表、字段或 endpoint，没有重写历史 migration。`RUNNING`、`ProductionMaterialReservation`、外协、样品及 Full 生产生命周期代码继续存在。历史 `RUNNING` 批次完成时不会重复 BOM 倒冲。

## Stage Commits

- `7d5129a` `feat(lite): simplify navigation and core workflows`
- `7c1b41d` `feat(lite): support direct planned production completion`
- `6829888` `feat(lite): streamline demand inventory and purchase views`
- `2c0ba08` `feat(lite): simplify finance and return experience`
- `6c33ee6` `feat(lite): finalize lightweight ERP experience`

## E2E Acceptance Matrix

1. 成品库存 20、订单 100，只对缺口 80 展开 BOM：`test_partial_inventory_reserves_only_available_and_plans_remaining`、`test_shared_part_purchase_shortage_is_globally_aggregated`。
2. 两个客户的同产品需求合并生产且 allocation 保留客户归属：`test_same_product_orders_merge_and_receive_different_eta`。
3. 16 条线、产品两套模具时同产品最多并行两份：`test_single_mold_prevents_parallel_and_two_molds_allow_parallel`。
4. 原料不足仍有理论排期且 ETA 标记不可靠：`test_inventory_is_not_promised_twice_and_bom_shortage_marks_eta_unreliable`、`test_material_available_runs_out_notes_shortage`。
5. `PurchaseCommitment` 改变未来材料供给和 ETA：`test_material_arrival_pushes_run_start`、`test_second_commitment_lot_sets_material_eta`。
6. `PLANNED` 直接完工倒冲 BOM、成品入库并重算：`test_lite_planned_run_direct_completion_backflushes_actual_quantity`。
7. 实际完工缺料返回 409 且库存不变：`test_lite_planned_run_direct_completion_rejects_material_shortage`。
8. 订单 100 分 40、60 两次出库后 `FULFILLED`：`test_partial_and_multi_product_shipping_updates_only_selected_lines`、`test_whole_order_shipping_fulfills_once_and_rejects_duplicate`。
9. 多产品订单只出其中一个产品的一部分：`test_partial_and_multi_product_shipping_updates_only_selected_lines`。
10. 退款、换货、restock true/false 保持库存/应收/成本：`test_return_restock_semantics_per_resolution`、`test_case1_interleaved_ship_refund_value_conservation` 至 `test_case4_restock_false_still_consumes_cost_pool`。
11. 应收 1000、收款 600、退货 OFFSET/REFUND_DUE 不重复消费余额：`test_partial_and_full_allocation_statuses`、`test_partial_payment_plus_large_refund_splits_credits`。
12. 备份、继续业务、恢复后回到快照事实：`test_restore_rebuilds_derived_state_and_creates_pre_restore_backup`、`test_schema22_roundtrip_preserves_stage5_financial_and_shipment_data`。
13. 并发确认、完工、出库、退货、收款等不产生负库存、重复出库、double reversal、状态复活或超额核销：`test_stage7_mysql_audit.py` 的确定性并发矩阵。

## Performance

Lite V1 沿用已验证的 planner。代表性 SQLite 数据集包含 120 个产品、500 个历史订单、20 个进行中订单和 16 条产线，`recalculate_production_plan` 实测为 **0.067 秒**，低于 3 秒报告线。目标部署规模为 100+ 产品、500 以内历史订单和不超过 5 个并发用户；不为追求 100ms 重写排产架构。

## Verification

- SQLite 全量：210 个测试通过，792 个 MySQL 专项测试跳过。
- MySQL 确定性审计：隔离的临时 MySQL 8.0 数据库完成 head migration，Stage 7 审计 791 个测试全部通过；容器和临时卷已删除，业务数据库未使用。
- Frontend：TypeScript typecheck、生产构建和 Vitest 全部通过；导航测试覆盖唯一 Lite 主导航以及旧 Full 分组隐藏规则。
- Alembic：`20260825_01` 为唯一 head。

## Known Limitations

- Lite 导航使用独立 `/lite-*` URL；旧 Full URL 作为隐藏兼容入口继续可访问。
- 外协和 Samples 没有物理删除，管理员通过历史 URL 仍可访问。
- 正常 Lite 流程不提供暂停/恢复/终止按钮；历史 `RUNNING` 数据仍可在完工页登记完成。

## Remaining Full-only Features

Samples、External Processing、Full/MES 式开工领料与终止结算、半成品/外协在途详细管理，以及其后端兼容 endpoint 和 schema。
