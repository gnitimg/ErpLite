# Stage 7 独立发布审计说明

Stage 7 是独立黑盒发布审计，不是 Stage 6 的延续开发，也不能由完成 Stage 6 的同一 Agent 宣布通过。

## 审计环境

- 使用独立 Agent，从 `develop` 的 Stage 6 最终 SHA 开始。
- 使用真实 MySQL 8、全新 clean database，并执行 `alembic upgrade head`。
- 不复用开发者本机业务库、SQLite 单测库或 Stage 6 进程状态。
- 通过真实 HTTP 服务和前端构建产物测试，不直接调用 Python endpoint 函数代替黑盒验证。
- 并发场景使用两个独立数据库 Session / HTTP client，并用 barrier 控制同时提交。

## 必做审计

1. 迁移：确认 `alembic heads` 只有一个 head，clean database 可升级到 head。
2. 后端：运行完整 pytest，并记录 passed、failed、duration。
3. 前端：运行 `pnpm typecheck` 和 `pnpm build`，两者必须 exit 0。
4. 备份：在 MySQL 上完成 schema 22 roundtrip；验证 PRE_RESTORE、重建失败 500、Stage 5 snapshot/credit/allocation 数据。
5. 并发：覆盖同物料出库、订单出库、销售退货、生产开工/完工、Payment allocation 和 CustomerCredit settle 的竞争路径。
6. HTTP/RBAC：用 ADMIN、OPERATOR、VIEWER、inactive user 和 emergency admin 走真实登录与关键接口。
7. 库存：验证盘盈/盘亏拆单、PART/PRODUCT 盘点、只读 ledger audit、原单冲销后的历史和口径。
8. 退货与财务：验证 REFUND/REPLACE、交错出库退货 snapshot、SALE_OUT reversal guard、CustomerCredit 状态。
9. Planner benchmark：在约定规模的数据集上记录全量重算耗时、数据库类型、CPU/内存和数据量；不要只写“足够快”。
10. 前端黑盒：至少检查登录、订单退货历史、库存盘点/对账、用户停用/恢复、备份失败提示和权限隐藏。

## 报告要求

报告必须附命令、环境、最终 SHA、可复现证据和所有失败项。此文件只定义审计方法，不表示 Stage 7 已通过，也不得提前写入 “Full Ready”。
