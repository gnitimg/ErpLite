"""鉴权与 RBAC 端到端测试。

经 TestClient 走真实 HTTP 中间件链（RBAC 门卫 + 审计广播），验证：
- 登录仅认 User 表与显式开启的应急管理员，旧 env 后门凭据彻底失效；
- /api/v1/users/me 无令牌/坏令牌返回 401，绝不再回落 ADMIN；
- 业务 API 按ADMIN / OPERATOR / VIEWER 执行角色门槛；
- 备份（含下载）仅 ADMIN；
- 操作日志用户名来自已验证 JWT；
- 生产环境缺少 ERP_JWT_SECRET 拒绝启动。
"""
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import app.main as main_module
from app.auth import (
    create_access_token,
    emergency_admin_credentials,
    required_role_for,
    validate_auth_config,
)
from app.database import Base, get_db
from app.models import OperationLog, User
from app.services import hash_password


client = TestClient(main_module.app)


@pytest.fixture()
def db(monkeypatch):
    # StaticPool + check_same_thread=False：TestClient 的工作线程与测试线程必须共享
    # 同一个内存库连接，否则各自看到的是空数据库。
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    # 依赖覆盖必须用干净签名的函数包装：sessionmaker 自身的 __init__ 带 **local_kw
    # 等形参，直接作为依赖会让 FastAPI 尝试注入它们（422 missing query local_kw）。
    def override_get_db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    main_module.app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(main_module, "SessionLocal", factory)
    yield factory
    main_module.app.dependency_overrides.pop(get_db, None)


def add_user(factory, username: str, role: str, password: str = "pass-123456") -> int:
    with factory() as session:
        user = User(
            username=username,
            password_hash=hash_password(password),
            display_name=username,
            role=role,
        )
        session.add(user)
        session.commit()
        session.refresh(user)
        return int(user.id)


def login_token(username: str, password: str) -> str | None:
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return response.json()["data"]["token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ───────────────────────── 登录 ─────────────────────────

def test_login_with_user_table_credentials(db):
    add_user(db, "op1", "OPERATOR")
    response = client.post("/api/v1/auth/login", json={"username": "op1", "password": "pass-123456"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["role"] == "OPERATOR"
    assert data["token"]


def test_login_wrong_password_rejected(db):
    add_user(db, "op1", "OPERATOR")
    response = client.post("/api/v1/auth/login", json={"username": "op1", "password": "wrong"})
    assert response.status_code == 401


def test_legacy_env_admin_backdoor_removed(db, monkeypatch):
    """即使环境里残留旧的 ERP_ADMIN_USER/ERP_ADMIN_PASSWORD，也不允许登录。"""
    monkeypatch.setenv("ERP_ADMIN_USER", "admin")
    monkeypatch.setenv("ERP_ADMIN_PASSWORD", "12345678")
    monkeypatch.delenv("ERP_ENABLE_EMERGENCY_ADMIN", raising=False)
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "12345678"})
    assert response.status_code == 401


# ───────────────────────── 应急管理员 ─────────────────────────

def test_emergency_admin_disabled_by_default(db, monkeypatch):
    monkeypatch.delenv("ERP_ENABLE_EMERGENCY_ADMIN", raising=False)
    monkeypatch.delenv("ERP_EMERGENCY_ADMIN_USER", raising=False)
    monkeypatch.delenv("ERP_EMERGENCY_ADMIN_PASSWORD", raising=False)
    assert emergency_admin_credentials() is None
    response = client.post("/api/v1/auth/login", json={"username": "emg", "password": "whatever-long-password"})
    assert response.status_code == 401


def test_emergency_admin_enabled_and_audited(db, monkeypatch):
    monkeypatch.setenv("ERP_ENABLE_EMERGENCY_ADMIN", "1")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_USER", "emg")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_PASSWORD", "break-glass-pass-123")
    response = client.post("/api/v1/auth/login", json={"username": "emg", "password": "break-glass-pass-123"})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["role"] == "ADMIN"
    with db() as session:
        logs = session.scalars(select(OperationLog).where(OperationLog.action == "应急管理员登录")).all()
        assert len(logs) == 1
        assert logs[0].username == "emg"
    # 应急管理员令牌可用于 users/me。
    me = client.get("/api/v1/users/me", headers=auth(data["token"]))
    assert me.status_code == 200
    assert me.json()["data"]["role"] == "ADMIN"


def test_emergency_admin_weak_password_rejected(db, monkeypatch):
    monkeypatch.setenv("ERP_ENABLE_EMERGENCY_ADMIN", "1")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_USER", "emg")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_PASSWORD", "short")
    assert emergency_admin_credentials() is None
    response = client.post("/api/v1/auth/login", json={"username": "emg", "password": "short"})
    assert response.status_code == 401


# ───────────────────────── users/me ─────────────────────────

def test_users_me_without_token_returns_401(db):
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_users_me_with_invalid_token_returns_401(db):
    response = client.get("/api/v1/users/me", headers=auth("not-a-jwt"))
    assert response.status_code == 401


def test_users_me_with_valid_token_returns_real_user(db):
    add_user(db, "viewer1", "VIEWER")
    token = login_token("viewer1", "pass-123456")
    response = client.get("/api/v1/users/me", headers=auth(token))
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["username"] == "viewer1"
    assert data["role"] == "VIEWER"


# ───────────────────────── RBAC 中间件 ─────────────────────────

def test_required_role_rules():
    assert required_role_for("/api/v1/auth/login", "POST") is None
    assert required_role_for("/api/health", "GET") is None
    # EventSource 无法携带 Authorization 头，实时刷新信号保持公开（不含业务数据）。
    assert required_role_for("/api/events", "GET") is None
    assert required_role_for("/api/orders", "GET") == "VIEWER"
    assert required_role_for("/api/orders", "POST") == "OPERATOR"
    assert required_role_for("/api/users", "GET") == "ADMIN"
    assert required_role_for("/api/backups/x.zip/download", "GET") == "ADMIN"
    assert required_role_for("/api/system/production-settings", "GET") == "VIEWER"
    assert required_role_for("/api/system/production-settings", "PUT") == "ADMIN"
    assert required_role_for("/api/system/print-settings", "PUT") == "ADMIN"
    assert required_role_for("/api/system/calendar/exceptions", "GET") == "VIEWER"
    assert required_role_for("/api/system/calendar/exceptions", "POST") == "OPERATOR"


def test_business_api_requires_login(db):
    response = client.get("/api/orders")
    assert response.status_code == 401
    assert response.json()["detail"] == "需要登录后操作"


def test_invalid_token_rejected_at_gateway(db):
    response = client.get("/api/orders", headers=auth("bad.token.value"))
    assert response.status_code == 401


def test_viewer_can_read_but_not_write(db):
    add_user(db, "viewer1", "VIEWER")
    token = login_token("viewer1", "pass-123456")
    reading = client.get("/api/orders", headers=auth(token))
    assert reading.status_code == 200
    writing = client.post("/api/parts", headers=auth(token), json={"sku": "V01", "name": "只读测试料"})
    assert writing.status_code == 403


def test_operator_write_allowed_and_audited_with_jwt_username(db):
    add_user(db, "op1", "OPERATOR")
    token = login_token("op1", "pass-123456")
    response = client.post("/api/parts", headers=auth(token), json={"sku": "P9001", "name": "审计测试料"})
    assert response.status_code == 201
    with db() as session:
        logs = session.scalars(
            select(OperationLog).where(OperationLog.path == "/api/parts", OperationLog.method == "POST")
        ).all()
        assert logs, "写操作必须留下审计日志"
        assert {log.username for log in logs} == {"op1"}


def test_backup_endpoints_admin_only(db):
    add_user(db, "viewer1", "VIEWER")
    add_user(db, "op1", "OPERATOR")
    add_user(db, "boss", "ADMIN")
    assert client.get("/api/backups").status_code == 401
    viewer_token = login_token("viewer1", "pass-123456")
    operator_token = login_token("op1", "pass-123456")
    admin_token = login_token("boss", "pass-123456")
    assert client.get("/api/backups", headers=auth(viewer_token)).status_code == 403
    assert client.get("/api/backups", headers=auth(operator_token)).status_code == 403
    assert client.get("/api/backups", headers=auth(admin_token)).status_code == 200
    # 备份下载同样仅 ADMIN；非 ADMIN 在网关即被拒绝。
    download_url = "/api/backups/not-exists.zip/download"
    assert client.get(download_url, headers=auth(operator_token)).status_code == 403


def test_user_management_requires_admin(db):
    add_user(db, "op1", "OPERATOR")
    operator_token = login_token("op1", "pass-123456")
    response = client.get("/api/users", headers=auth(operator_token))
    assert response.status_code == 403


def test_one_of_two_active_admins_can_be_deactivated(db):
    first_id = add_user(db, "admin1", "ADMIN")
    second_id = add_user(db, "admin2", "ADMIN")
    token = login_token("admin1", "pass-123456")

    response = client.put(
        f"/api/users/{second_id}",
        headers=auth(token),
        json={"display_name": "admin2", "role": "ADMIN", "active": False},
    )

    assert response.status_code == 200
    with db() as session:
        assert session.get(User, first_id).active is True
        assert session.get(User, second_id).active is False


def test_last_active_admin_cannot_deactivate_self(db):
    admin_id = add_user(db, "admin1", "ADMIN")
    token = login_token("admin1", "pass-123456")

    response = client.put(
        f"/api/users/{admin_id}",
        headers=auth(token),
        json={"display_name": "admin1", "role": "ADMIN", "active": False},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "系统必须至少保留一个启用的管理员账号。"


def test_last_active_admin_cannot_downgrade_self(db):
    admin_id = add_user(db, "admin1", "ADMIN")
    token = login_token("admin1", "pass-123456")

    response = client.put(
        f"/api/users/{admin_id}",
        headers=auth(token),
        json={"display_name": "admin1", "role": "OPERATOR", "active": True},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "系统必须至少保留一个启用的管理员账号。"


def test_inactive_users_are_listed_and_can_be_reactivated(db):
    add_user(db, "admin1", "ADMIN")
    operator_id = add_user(db, "operator1", "OPERATOR")
    with db() as session:
        session.get(User, operator_id).active = False
        session.commit()
    token = login_token("admin1", "pass-123456")

    listed = client.get("/api/users", headers=auth(token))

    assert listed.status_code == 200
    inactive = next(row for row in listed.json() if row["id"] == operator_id)
    assert inactive["active"] is False

    reactivated = client.put(
        f"/api/users/{operator_id}",
        headers=auth(token),
        json={"display_name": "operator1", "role": "OPERATOR", "active": True},
    )
    assert reactivated.status_code == 200
    assert login_token("operator1", "pass-123456")


# ───────────────────────── JWT 密钥配置 ─────────────────────────

def test_production_refuses_to_start_without_secret(monkeypatch):
    monkeypatch.setenv("ERP_ENV", "production")
    monkeypatch.delenv("ERP_JWT_SECRET", raising=False)
    with pytest.raises(RuntimeError):
        validate_auth_config()


def test_production_starts_with_secret(monkeypatch):
    monkeypatch.setenv("ERP_ENV", "production")
    monkeypatch.setenv("ERP_JWT_SECRET", "a-proper-random-secret")
    monkeypatch.delenv("ERP_ENABLE_EMERGENCY_ADMIN", raising=False)
    validate_auth_config()


def test_token_roundtrip_in_same_process(db):
    user_id = add_user(db, "u7", "OPERATOR")
    token = create_access_token(user_id, "u7", "OPERATOR", "U7")
    response = client.get("/api/orders", headers=auth(token))
    # 有效签名 + 数据库中真实存在的 active 用户：放行（列表可能为空）。
    assert response.status_code == 200


# ───────────────────── 角色与状态的即时生效 ─────────────────────

def test_role_change_takes_effect_immediately(db):
    """数据库里的角色对已签发令牌立即生效，不等令牌过期。"""
    add_user(db, "op1", "OPERATOR")
    token = login_token("op1", "pass-123456")
    assert client.post("/api/parts", headers=auth(token), json={"sku": "X1", "name": "降级前"}).status_code == 201
    with db() as session:
        user = session.scalar(select(User).where(User.username == "op1"))
        user.role = "VIEWER"
        session.commit()
    assert client.get("/api/orders", headers=auth(token)).status_code == 200
    assert client.post("/api/parts", headers=auth(token), json={"sku": "X2", "name": "降级后"}).status_code == 403


def test_deactivated_user_rejected_immediately(db):
    add_user(db, "op1", "OPERATOR")
    token = login_token("op1", "pass-123456")
    assert client.get("/api/orders", headers=auth(token)).status_code == 200
    with db() as session:
        user = session.scalar(select(User).where(User.username == "op1"))
        user.active = False
        session.commit()
    assert client.get("/api/orders", headers=auth(token)).status_code == 401


# ───────────────────── 应急管理员令牌时效 ─────────────────────

def test_emergency_admin_token_short_ttl(db, monkeypatch):
    monkeypatch.setenv("ERP_ENABLE_EMERGENCY_ADMIN", "1")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_USER", "emg")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_PASSWORD", "break-glass-pass-123")
    from app.auth import verify_token
    token = login_token("emg", "break-glass-pass-123")
    payload = verify_token(token)
    assert 0 < payload["exp"] - payload["iat"] <= 2 * 3600


def test_emergency_token_dies_when_switch_turned_off(db, monkeypatch):
    monkeypatch.setenv("ERP_ENABLE_EMERGENCY_ADMIN", "1")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_USER", "emg")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_PASSWORD", "break-glass-pass-123")
    token = login_token("emg", "break-glass-pass-123")
    assert client.get("/api/orders", headers=auth(token)).status_code == 200
    # 关闭开关后，未过期的令牌也立即失效
    monkeypatch.delenv("ERP_ENABLE_EMERGENCY_ADMIN")
    assert client.get("/api/orders", headers=auth(token)).status_code == 401
    assert client.get("/api/v1/users/me", headers=auth(token)).status_code == 401


def test_require_admin_uses_current_database_role(db):
    """网关按数据库放行 ADMIN 后，endpoint 内的 require_admin 必须得出同一结论。"""
    add_user(db, "op1", "OPERATOR")
    token = login_token("op1", "pass-123456")
    # 库里升为 ADMIN → 同一令牌访问用户管理 200（此前 endpoint 会按 JWT 旧角色 403）
    with db() as session:
        user = session.scalar(select(User).where(User.username == "op1"))
        user.role = "ADMIN"
        session.commit()
    assert client.get("/api/users", headers=auth(token)).status_code == 200
    # 降回 VIEWER → 同一令牌 403
    with db() as session:
        user = session.scalar(select(User).where(User.username == "op1"))
        user.role = "VIEWER"
        session.commit()
    assert client.get("/api/users", headers=auth(token)).status_code == 403


def test_emergency_admin_username_rotation(db, monkeypatch):
    """轮换应急管理员用户名后，旧用户名的未过期令牌立即失效。"""
    monkeypatch.setenv("ERP_ENABLE_EMERGENCY_ADMIN", "1")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_USER", "emergency_a")
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_PASSWORD", "break-glass-pass-123")
    old_token = login_token("emergency_a", "break-glass-pass-123")
    assert client.get("/api/orders", headers=auth(old_token)).status_code == 200
    # 用户名 A → B：A 的令牌作废，B 可正常登录
    monkeypatch.setenv("ERP_EMERGENCY_ADMIN_USER", "emergency_b")
    assert client.get("/api/orders", headers=auth(old_token)).status_code == 401
    assert client.get("/api/v1/users/me", headers=auth(old_token)).status_code == 401
    new_token = login_token("emergency_b", "break-glass-pass-123")
    assert client.get("/api/orders", headers=auth(new_token)).status_code == 200
