from pathlib import Path
import asyncio
import json
import sys


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from fastapi import Request
from fastapi.responses import JSONResponse

from app.main import broadcast_successful_writes, change_events


def make_request(method: str, path: str, client_id: str = "") -> Request:
    headers = []
    if client_id:
        headers.append((b"x-erp-client-id", client_id.encode()))
    return Request(
        {
            "type": "http",
            "method": method,
            "path": path,
            "headers": headers,
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 12345),
            "scheme": "http",
        }
    )


def test_successful_write_broadcasts_change_signal(monkeypatch):
    class AuditSession:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def add(self, _row): pass
        def commit(self): pass

    monkeypatch.setattr("app.main.SessionLocal", AuditSession)
    queue = change_events.subscribe()
    try:
        async def call_next(_request):
            return JSONResponse({"ok": True}, status_code=201)

        response = asyncio.run(
            broadcast_successful_writes(
                make_request("POST", "/api/parts", "client-a"),
                call_next,
            )
        )
        assert response.status_code == 201
        event = json.loads(queue.get_nowait())
        # 公开信号不携带业务信息（无 path/method），只标识来源与时间。
        assert set(event) == {"id", "source", "occurred_at"}
        assert event["source"] == "client-a"
    finally:
        change_events.unsubscribe(queue)


def test_failed_write_does_not_broadcast(monkeypatch):
    class AuditSession:
        def __enter__(self): return self
        def __exit__(self, *_args): return False
        def add(self, _row): pass
        def commit(self): pass

    monkeypatch.setattr("app.main.SessionLocal", AuditSession)
    queue = change_events.subscribe()
    try:
        async def call_next(_request):
            return JSONResponse({"detail": "failed"}, status_code=401)

        response = asyncio.run(
            broadcast_successful_writes(
                make_request("POST", "/api/v1/auth/login", "client-b"),
                call_next,
            )
        )
        assert response.status_code == 401
        assert queue.empty()
    finally:
        change_events.unsubscribe(queue)
