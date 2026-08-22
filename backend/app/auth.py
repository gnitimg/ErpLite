import hmac
import hashlib
import base64
import json
import logging
import os
import secrets
import time

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


logger = logging.getLogger("uvicorn.error")

TOKEN_TTL_SECONDS = 86400 * 7

# Break-glass 应急管理员令牌只活 2 小时，且开关一关立即失效（见 current_role_for）。
EMERGENCY_TOKEN_TTL_SECONDS = 3600 * 2

# Break-glass 应急管理员密码的最小长度；弱口令直接拒绝启用。
EMERGENCY_ADMIN_MIN_PASSWORD_LENGTH = 12

ROLE_RANK = {"VIEWER": 0, "OPERATOR": 1, "ADMIN": 2}

# 无需登录即可访问的路径：登录本身、健康检查、实时刷新信号（不含业务数据）。
PUBLIC_API_PATHS = {"/api/v1/auth/login", "/api/health", "/api/events"}

# 仅 ADMIN 可访问（任意方法）：用户管理、备份全生命周期。
ADMIN_ONLY_PREFIXES = ("/api/users", "/api/backups")

# 系统级设置：读取开放给登录用户，修改仅 ADMIN。
ADMIN_WRITE_PREFIXES = ("/api/system/production-settings", "/api/system/print-settings")

# 未认证请求在审计日志中显示的用户名。
ANONYMOUS_USERNAME = "未登录"

_ephemeral_secret: bytes | None = None


def _get_secret() -> bytes:
    """JWT 签名密钥：优先环境变量；未配置时生成进程内随机密钥并告警。

    随机密钥意味着重启后所有已发令牌失效——这是开发模式可接受的降级，
    生产环境必须配置 ERP_JWT_SECRET（见 validate_auth_config，会拒绝启动）。
    绝不使用源码中的公开默认值。
    """
    global _ephemeral_secret
    configured = os.getenv("ERP_JWT_SECRET", "").strip()
    if configured:
        return configured.encode("utf-8")
    if _ephemeral_secret is None:
        _ephemeral_secret = secrets.token_bytes(32)
        logger.warning(
            "ERP_JWT_SECRET 未配置：已生成临时随机密钥，重启后所有登录令牌将失效。生产环境必须设置 ERP_JWT_SECRET。"
        )
    return _ephemeral_secret


def validate_auth_config() -> None:
    """启动时校验鉴权配置；生产环境缺少 ERP_JWT_SECRET 时拒绝启动。"""
    environment = os.getenv("ERP_ENV", "dev").strip().lower()
    if environment in {"production", "prod"}:
        if not os.getenv("ERP_JWT_SECRET", "").strip():
            raise RuntimeError("生产环境（ERP_ENV=production）必须配置 ERP_JWT_SECRET，拒绝启动。")
        if os.getenv("ERP_ENABLE_EMERGENCY_ADMIN", "").strip() == "1" and emergency_admin_credentials() is None:
            raise RuntimeError("ERP_ENABLE_EMERGENCY_ADMIN=1 但应急管理员用户名/密码未配置或强度不足，拒绝启动。")


def emergency_admin_credentials() -> tuple[str, str] | None:
    """Break-glass 应急管理员：默认关闭，显式开启且凭据满足强度要求时才可用。"""
    if os.getenv("ERP_ENABLE_EMERGENCY_ADMIN", "").strip() != "1":
        return None
    username = os.getenv("ERP_EMERGENCY_ADMIN_USER", "").strip()
    password = os.getenv("ERP_EMERGENCY_ADMIN_PASSWORD", "")
    if not username or not password:
        logger.warning("ERP_ENABLE_EMERGENCY_ADMIN=1 但未配置 ERP_EMERGENCY_ADMIN_USER/ERP_EMERGENCY_ADMIN_PASSWORD，应急账号未启用。")
        return None
    if len(password) < EMERGENCY_ADMIN_MIN_PASSWORD_LENGTH:
        logger.warning("应急管理员密码长度不足 %d 位，应急账号未启用。", EMERGENCY_ADMIN_MIN_PASSWORD_LENGTH)
        return None
    return username, password


def matches_emergency_admin(username: str, password: str, credentials: tuple[str, str]) -> bool:
    return (
        hmac.compare_digest(username.encode("utf-8"), credentials[0].encode("utf-8"))
        and hmac.compare_digest(password.encode("utf-8"), credentials[1].encode("utf-8"))
    )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding < 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def create_access_token(
    user_id: int, username: str, role: str, display_name: str = "", ttl_seconds: int | None = None
) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "display_name": display_name,
        "iat": int(time.time()),
        "exp": int(time.time()) + (ttl_seconds or TOKEN_TTL_SECONDS),
    }
    h = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    p = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    sig = hmac.new(_get_secret(), f"{h}.{p}".encode("utf-8"), hashlib.sha256).digest()
    s = _b64url_encode(sig)
    return f"{h}.{p}.{s}"


def verify_token(token: str) -> dict:
    parts = token.split(".")
    if len(parts) != 3:
        raise HTTPException(401, "无效的令牌格式")
    h, p, s = parts
    try:
        signature = _b64url_decode(s)
        payload_bytes = _b64url_decode(p)
    except Exception as error:
        # 非法 base64 / 非法 JSON 一律按无效令牌处理，绝不让畸形输入变成 500。
        raise HTTPException(401, "无效的令牌格式") from error
    expected_sig = hmac.new(_get_secret(), f"{h}.{p}".encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(signature, expected_sig):
        raise HTTPException(401, "令牌签名无效")
    try:
        payload = json.loads(payload_bytes)
    except Exception as error:
        raise HTTPException(401, "无效的令牌格式") from error
    if not isinstance(payload, dict):
        raise HTTPException(401, "无效的令牌格式")
    if payload.get("exp", 0) < int(time.time()):
        raise HTTPException(401, "令牌已过期")
    return payload


def extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def authenticated_username(request: Request) -> str:
    """审计用：从已验证的 JWT 取用户名，取不到时明确标记为未登录。"""
    token = extract_token(request)
    if not token:
        return ANONYMOUS_USERNAME
    try:
        return str(verify_token(token).get("username") or ANONYMOUS_USERNAME)[:120]
    except HTTPException:
        return ANONYMOUS_USERNAME


def current_role_for(payload: dict, db: Session) -> str | None:
    """按数据库当前状态解析令牌的角色；返回 None 表示令牌已失效。

    - 普通用户：必须仍存在且 active，角色取数据库当前值（改角色/停用立即生效，
      不等 7 天令牌过期）；
    - 应急管理员令牌：开关关闭或凭据不再满足强度要求时立即作废。
    """
    try:
        user_id = int(payload.get("sub", "0") or 0)
    except (TypeError, ValueError):
        return None
    if user_id > 0:
        user = db.get(User, user_id)
        if not user or not user.active:
            return None
        return user.role
    if payload.get("role") == "ADMIN":
        return "ADMIN" if emergency_admin_credentials() is not None else None
    return None


def get_current_user(request: Request, db: Session = None) -> dict:
    token = extract_token(request)
    if not token:
        raise HTTPException(401, "未提供认证令牌")
    return verify_token(token)


def require_user(request: Request) -> dict:
    token = extract_token(request)
    if not token:
        raise HTTPException(401, "需要登录后操作")
    return verify_token(token)


def require_admin(request: Request) -> dict:
    payload = require_user(request)
    if payload.get("role") != "ADMIN":
        raise HTTPException(403, "需要管理员权限")
    return payload


def required_role_for(path: str, method: str) -> str | None:
    """返回访问该 API 所需的最低角色；None 表示无需登录。

    规则：
    - 公开路径（登录、健康检查、实时刷新信号）任何人可访问；
    - 用户管理与备份全生命周期仅 ADMIN；
    - 系统级设置（生产设置、打印设置）修改仅 ADMIN，读取放开；
    - 其余 GET 只需登录（VIEWER 可读），写操作需要 OPERATOR。
    """
    if path in PUBLIC_API_PATHS:
        return None
    if path.startswith(ADMIN_ONLY_PREFIXES):
        return "ADMIN"
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return "VIEWER"
    if path.startswith(ADMIN_WRITE_PREFIXES):
        return "ADMIN"
    return "OPERATOR"


def role_allows(role: str | None, required: str | None) -> bool:
    if required is None:
        return True
    return ROLE_RANK.get(role or "VIEWER", 0) >= ROLE_RANK[required]


def load_user(db: Session, user_id: int) -> User | None:
    user = db.scalar(select(User).where(User.id == user_id))
    return user if user and user.active else None
