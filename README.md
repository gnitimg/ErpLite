# 简仓 ERP

一套面向小型仓库与轻量组装业务的 ERP。前端完整采用 MIT 许可的 **V3 Admin Vite** 后台模板，保留主题、标签页、布局设置、响应式侧栏和登录页，仅在路由层停用模板自带的演示页面。后端采用 FastAPI + SQLAlchemy，数据库为 MySQL 8。

## 功能

- 零件档案：编码、规格、单位、成本与安全库存。
- 产品与 BOM：用表格选择组成零件和单台用量。
- 采购入库、普通成品入库、按 BOM 生产入库。
- 零件或产品手工出库，严格禁止负库存。
- 客户订单：草稿、确认、取消和销售出库。
- 客单按“要求交期”由近到远分配产品库存；库存不足时自动汇总 BOM 零件缺口，零件齐备后生产入库并预留成品，再执行客单出库。
- 产品档案维护成本价和参考价；新建客单默认带入参考价，允许逐单修改成交价，并展示折扣率与优惠金额。
- 零件默认采用库存备料，少数零件可标记为“按单即买”，并在客单缺料明细中区分显示。
- 客单列表支持按客单号、客户名称/电话模糊搜索，并可在筛选侧栏按状态和日期范围过滤。
- 实时库存、低库存预警、库存成本与完整流水。
- 库存管理按零件库存、产品库存、产品生产、出入库作业和库存流水拆分；流水摘要留在表格，完整字段在右侧详情栏查看。
- 产品数量统一为正整数（客单、生产和产品出入库均进行前后端校验），BOM 零件用量仍支持小数。
- 出入库作业支持按单个零件/产品办理，也支持按客户订单自动补齐缺口零件或将已预留产品一次性出库。
- 侧栏“物料目录”包含零件目录、产品与 BOM、样品库存；样品新建时默认 300 件，可编辑，库存变更会保留为“样品调整”流水。
- 工作台使用“备货任务”统一展示待采购、待生产和待出库任务，并可在卡片右上角按任务类型或逾期状态筛选。
- 工作台集中显示待购买零件、待生产产品、待出库客单和库存预警。
- 库存数量不显示负数；不足时使用红色状态。数量达到 10,000 后按“万”显示，例如 `15820` 显示为 `1.582万`，数据库仍保存原始数值。
- 数据备份：一键创建、列表筛选、下载 ZIP 快照，并可从指定快照快速恢复。
- 工作台：关键指标、最近库存动态和快捷入口。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Element Plus、Pinia、Vue Router、V3 Admin Vite 完整模板。
- 后端：Python 3、FastAPI、SQLAlchemy、PyMySQL。
- 数据库：MySQL 8，默认数据库 `lite_erp`。

## 1. 本机 MySQL

默认使用电脑上已安装的 MySQL 8.4 程序，在项目目录创建隔离数据目录并监听 `127.0.0.1:3307`。它不会修改或停止已有的 3306 MySQL 服务。首次启动会自动创建 `lite_erp` 数据库及独立用户。

如需单独管理数据库进程：

```powershell
.\mysql-local.ps1 start
.\mysql-local.ps1 status
.\mysql-local.ps1 stop
```

若要改用已有或远程 MySQL，只需修改 `.env` 中的主机、端口、数据库和账号，并自行执行 `database\init_mysql.sql`。

## 2. 安装与构建

```powershell
Set-Location F:\DockerDesktop\erp
.\setup.ps1
```

## 3. 启动

前台启动：

```powershell
.\start.ps1
```

后台启动与管理：

```powershell
.\service.ps1 start
.\service.ps1 status
.\service.ps1 logs
.\service.ps1 stop
```

- ERP：http://localhost:8000
- API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/api/health

默认登录信息：用户名 `admin`，密码 `12345678`。账号可在 `.env` 中修改；当前本机版本暂未启用验证码。

## 开发调试

后端支持在 `backend\app` 目录直接运行，不会再出现相对导入错误：

```powershell
Set-Location F:\DockerDesktop\erp\backend\app
..\..\.venv\Scripts\python.exe main.py
```

另开一个 PowerShell 启动完整模板开发服务器：

```powershell
Set-Location F:\DockerDesktop\erp\frontend
corepack pnpm dev
```

- 开发页面：http://localhost:3333
- 开发代理目标：http://localhost:8000

MySQL 暂未启动时，页面与无验证码登录仍可使用；依赖库存数据的接口会明确返回 HTTP 503“数据库尚未就绪”，不会让整个后端启动失败。

## 数据备份与恢复

登录后从“系统管理 → 数据备份”进入管理页：

1. 点击“立即备份”创建完整业务数据快照。
2. 可下载 ZIP 文件并复制到项目目录之外长期留存。
3. 恢复时需要输入完整备份文件名进行二次确认。
4. 系统会在恢复前自动创建一份“恢复前自动备份”，随后在单个数据库事务中替换数据；任一步骤失败都会回滚本次恢复。

备份覆盖零件/产品、BOM、客单、库存结存及库存流水，文件默认保存在项目根目录的 `backups\`，该目录已加入 `.gitignore`。备份文件含业务数据，请按敏感数据管理，不要提交到 Git 仓库。

### 客单库存流程

1. 新建客单时填写要求交期；产品成交价默认等于产品参考价，但可按本单修改。
2. 确认客单后，系统按要求交期、订单日期、客单创建顺序分配现有产品库存并记录预留。
3. 产品不足时按 BOM 汇总零件需求：库存备料零件从现有库存取用，按单即买零件在缺料清单中提示采购。
4. 零件齐备后点击“重新检查并生产”，系统生成生产入库流水、扣减零件并增加成品，然后按交期重新分配预留。
5. 只有产品全部预留的客单才能出库；取消或完成客单后会重新计算其他客单的预留顺序。

客单表格只显示摘要，点击操作栏“详情”从右侧打开客单工作区，并按“订单概况、产品与价格、库存与交付、零件与备料”四个页签展示；确认、备货、出库等关键操作固定在顶部。主题配置位于右上角头像菜单的“主题设置”，该页面不出现在侧栏，并提供即时预览。

## 项目结构

```text
backend/app/        FastAPI、SQLAlchemy 模型与库存业务逻辑
database/           MySQL 初始化脚本
frontend/           完整 V3 Admin Vite 模板与 ERP 页面
backups/            运行时生成的数据备份（不提交 Git）
docs/DATA_MODEL.md  数据表与业务约束说明
setup.ps1           安装依赖并构建前端
start.ps1           前台启动
service.ps1         后台启动、停止、状态与日志
mysql-local.ps1     隔离的本机 MySQL 启停脚本
```

## 核心 API

| 模块 | 接口 |
|---|---|
| 登录 | `POST /api/v1/auth/login` |
| 工作台 | `GET /api/dashboard` |
| 样品库存 | `GET/POST /api/samples`、`PUT/DELETE /api/samples/{id}` |
| 零件 | `GET/POST /api/parts`、`PUT/DELETE /api/parts/{id}` |
| 产品/BOM | `GET/POST /api/products`、`PUT/DELETE /api/products/{id}` |
| 库存 | `GET /api/inventory` |
| 出入库 | `POST /api/stock/inbound`、`POST /api/stock/outbound` |
| 流水 | `GET /api/stock/transactions` |
| 客单 | `GET/POST /api/orders`，以及 `confirm/fulfill/cancel` 动作 |
| 数据备份 | `GET/POST /api/backups`、`GET /api/backups/{filename}/download`、`POST /api/backups/{filename}/restore` |

### 列表筛选参数

| 接口 | 参数 | 说明 |
|---|---|---|
| `GET /api/parts` | `keyword`、`stock_status` | `keyword` 模糊匹配零件 SKU/名称/规格；`stock_status` 可选 `LOW`（库存小于等于安全库存）或 `NORMAL`（库存高于安全库存） |
| `GET /api/products` | `keyword`、`stock_status`、`bom_status` | `keyword` 模糊匹配产品 SKU/名称/规格；库存状态同上；`bom_status` 可选 `CONFIGURED`（已配置 BOM）或 `EMPTY`（未配置 BOM） |
| `GET /api/inventory` | `keyword`、`kind`、`stock_status`、`low_stock` | `keyword` 模糊匹配物料 SKU/名称/规格；`kind` 可选 `PART` 或 `PRODUCT`；库存状态同上。保留 `low_stock=true` 兼容旧调用，同时传入时以 `stock_status` 为准 |
| `GET /api/stock/transactions` | `keyword`、`transaction_type`、`start_date`、`end_date`、`limit` | `keyword` 模糊匹配流水号、物料 SKU/名称或备注；类型精确匹配（如 `PURCHASE_IN`、`ASSEMBLY_IN`、`MANUAL_IN`、`MANUAL_OUT`、`SALE_OUT`、`OPENING`）；日期格式为 `YYYY-MM-DD` 且包含起止当日；`limit` 范围为 1–500 |

## 当前边界

该版本适合单仓、小团队和基础 BOM 组装，不包含财务总账、税务、批次/序列号、多仓调拨和复杂权限。后续可在现有库存流水模型上继续扩展。
