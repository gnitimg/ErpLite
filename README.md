<p align="center">
  <img alt="logo" width="120" height="120" src="./frontend/src/common/assets/images/layouts/logo.png">
</p>

<h1 align="center">简仓 ERP</h1>

<p align="center">
  面向小型仓库与轻量组装业务的轻量 ERP 系统
</p>

<p align="center">
  <a href="./README.zh-CN.md"><img alt="Chinese" src="https://img.shields.io/badge/文档-简体中文-green"></a>
  <img alt="License" src="https://img.shields.io/badge/license-MIT-blue.svg">
  <img alt="Vue" src="https://img.shields.io/badge/Vue-3.5-42b883">
  <img alt="FastAPI" src="https://img.shields.io/badge/FastAPI-0.116-009688">
  <img alt="MySQL" src="https://img.shields.io/badge/MySQL-8-4479a1">
</p>

## 简介

简仓 ERP 是一套面向**小型仓库**与**轻量组装业务**的进销存与客户订单管理系统。前端完整采用 MIT 许可的 [V3 Admin Vite](https://github.com/un-pany/v3-admin-vite) 后台模板（保留主题、标签页、布局设置、响应式侧栏和登录页），后端为 FastAPI + SQLAlchemy，数据库使用 MySQL 8。

- 零件与产品统一物料管理，产品支持 BOM 组装
- 采购入库、按 BOM 生产入库、手工出库、销售出库，全程流水可追溯
- 严格禁止负库存，成本价实时核算
- 客户订单草稿 → 确认 → 出库 → 完成全流程

## 功能特性

- **零件档案**：编码、规格、单位、成本与安全库存管理
- **产品与 BOM**：表格化选择组成零件并设置单台用量
- **入库管理**：采购入库、普通成品入库、按 BOM 生产入库（自动扣减零件）
- **出库管理**：零件 / 产品手工出库，严格禁止负库存
- **客户订单**：草稿、确认、取消与销售出库全流程
- **库存中心**：实时库存、低库存预警、库存成本与完整流水
- **工作台**：关键指标、最近库存动态和快捷入口

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 · TypeScript · Vite · Element Plus · Pinia · Vue Router · V3 Admin Vite 模板 |
| 后端 | Python · FastAPI · SQLAlchemy 2.0 · PyMySQL |
| 数据库 | MySQL 8（默认数据库 `lite_erp`） |

## 快速开始

### 环境要求

- Python 3.10+
- Node.js 20.19+ / 22.12+，pnpm 10+
- MySQL 8

### 1. 初始化 MySQL

项目使用独立的 `lite_erp` 数据库用户，请用 MySQL 管理员账号执行：

```powershell
mysql -u root -p < database\init_mysql.sql
```

默认应用数据库密码写在本地 `.env` 中。正式使用前建议同时修改 `.env` 与 `database/init_mysql.sql` 中的密码。

### 2. 安装与构建

```powershell
cd F:\DockerDesktop\erp
.\setup.ps1
```

该脚本会创建 `.venv` 虚拟环境、安装后端依赖，并通过 pnpm 安装前端依赖并执行生产构建。

### 3. 启动

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

### 4. 访问

- ERP：<http://localhost:8000>
- API 文档：<http://localhost:8000/docs>
- 健康检查：<http://localhost:8000/api/health>

**默认登录信息**：用户名 `admin`，密码 `12345678`，验证码 `1234`。账号可在 `.env` 中修改。

## 环境变量

参考 [`.env.example`](./.env.example)，复制为 `.env` 后按需修改：

| 变量 | 说明 | 默认值 |
|---|---|---|
| `ERP_MYSQL_HOST` | MySQL 主机 | `127.0.0.1` |
| `ERP_MYSQL_PORT` | MySQL 端口 | `3306` |
| `ERP_MYSQL_DATABASE` | 数据库名 | `lite_erp` |
| `ERP_MYSQL_USER` | 数据库用户 | `lite_erp` |
| `ERP_MYSQL_PASSWORD` | 数据库密码 | 见 `.env.example` |
| `ERP_ADMIN_USER` | 管理账号 | `admin` |
| `ERP_ADMIN_PASSWORD` | 管理密码 | `12345678` |

## 项目结构

```text
backend/
  app/              FastAPI 应用：路由、SQLAlchemy 模型、库存业务逻辑
database/
  init_mysql.sql    MySQL 初始化脚本（建库、建用户、授权）
frontend/           完整 V3 Admin Vite 模板与 ERP 页面
docs/
  DATA_MODEL.md     数据表与业务约束说明
setup.ps1           安装依赖并构建前端
start.ps1           前台启动
service.ps1         后台启动、停止、状态与日志
```

## 核心 API

| 模块 | 接口 |
|---|---|
| 登录 | `GET /api/v1/auth/captcha`、`POST /api/v1/auth/login` |
| 工作台 | `GET /api/dashboard` |
| 零件 | `GET/POST /api/parts`、`PUT/DELETE /api/parts/{id}` |
| 产品 / BOM | `GET/POST /api/products`、`PUT/DELETE /api/products/{id}` |
| 库存 | `GET /api/inventory` |
| 出入库 | `POST /api/stock/inbound`、`POST /api/stock/outbound` |
| 流水 | `GET /api/stock/transactions` |
| 客单 | `GET/POST /api/orders`，以及 `confirm` / `fulfill` / `cancel` 动作 |

## 当前边界与规划

该版本适合单仓、小团队和基础 BOM 组装，不包含财务总账、税务、批次 / 序列号、多仓调拨和复杂权限。后续可在现有库存流水模型上扩展：

- 多仓库与库存调拨
- 批次 / 序列号追溯
- 采购管理（供应商、采购单）
- 预占库存与可用库存区分
- 更细粒度的用户与权限控制

## 致谢与许可

- 前端模板 [V3 Admin Vite](https://github.com/un-pany/v3-admin-vite) · MIT
- 依赖与致谢详见 [THIRD_PARTY_NOTICES.md](./THIRD_PARTY_NOTICES.md)
