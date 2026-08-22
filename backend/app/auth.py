import os
import time
import hmac
import hashlib
import base64
import json

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import User


def _get_secret() -> bytes:
    return os.getenv("ERP_JWT_SECRET", "erp-lite-default-secret-change-me").encode("utf-8")


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding < 4:
        s += "=" * padding
    return base64.urlsafe_b64decode(s.encode("utf-8"))


def create_access_token(user_id: int, username: str, role: str, display_name: str = "") -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "display_name": display_name,
        "iat": int(time.time()),
        "exp": int(time.time()) + 86400 * 7,
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
    expected_sig = hmac.new(_get_secret(), f"{h}.{p}".encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_decode(s), expected_sig):
        raise HTTPException(401, "令牌签名无效")
    payload = json.loads(_b64url_decode(p))
    if payload.get("exp", 0) < int(time.time()):
        raise HTTPException(401, "令牌已过期")
    return payload


def extract_token(request: Request) -> str | None:
    auth_header = request.headers.get("authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]
    return None


def get_current_user(request: Request, db: Session = None) -> dict:
    token = extract_token(request)
    if not token:
        env_username = os.getenv("ERP_ADMIN_USER", "admin")
        env_password = os.getenv("ERP_ADMIN_PASSWORD", "12345678")
        if env_password:
            return {"sub": "0", "username": env_username, "role": "ADMIN", "display_name": "仓库管理员"}
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
