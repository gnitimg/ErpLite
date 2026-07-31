# 简仓 ERP

一套面向小型仓库与轻量组装业务的 ERP。前端完整采用 MIT 许可的 **V3 Admin Vite** 后台模板，保留主题、标签页、布局设置、响应式侧栏和登录页，仅在路由层停用模板自带的演示页面。后端采用 FastAPI + SQLAlchemy，数据库为 MySQL 8。

## 功能

- 零件档案：编码、规格、单位、成本与安全库存。
- 产品与 BOM：用表格选择组成零件和单台用量。
- 采购入库、普通成品入库、按 BOM 生产入库。
- 零件或产品手工出库，严格禁止负库存。
- 客户订单：草稿、确认、取消和销售出库。
- 客单列表支持按客单号、客户名称/电话模糊搜索，并可在筛选侧栏按状态和日期范围过滤。
- 实时库存、低库存预警、库存成本与完整流水。
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

## 项目结构

```text
backend/app/        FastAPI、SQLAlchemy 模型与库存业务逻辑
database/           MySQL 初始化脚本
frontend/           完整 V3 Admin Vite 模板与 ERP 页面
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
| 零件 | `GET/POST /api/parts`、`PUT/DELETE /api/parts/{id}` |
| 产品/BOM | `GET/POST /api/products`、`PUT/DELETE /api/products/{id}` |
| 库存 | `GET /api/inventory` |
| 出入库 | `POST /api/stock/inbound`、`POST /api/stock/outbound` |
| 流水 | `GET /api/stock/transactions` |
| 客单 | `GET/POST /api/orders`，以及 `confirm/fulfill/cancel` 动作 |

## 当前边界

该版本适合单仓、小团队和基础 BOM 组装，不包含财务总账、税务、批次/序列号、多仓调拨和复杂权限。后续可在现有库存流水模型上继续扩展。
