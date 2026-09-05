"""路由层：轻薄协议 adapter（issue #3 诊断端点；#5 将接入 SessionApplication）。"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Response, WebSocket

import app.models  # noqa: F401  # 确保 ORM 元数据注册
from app.config import get_settings
from app.db.session import create_engine as create_db_engine
from app.diagnostics.metrics import metrics

router = APIRouter()


@router.get("/health")
async def health_legacy() -> dict[str, Any]:
    """向后兼容别名 → live。"""
    return {"status": "ok"}


@router.get("/health/live")
async def health_live() -> dict[str, Any]:
    return {"status": "ok"}


@router.get("/health/ready")
async def health_ready() -> Response:
    from fastapi.responses import JSONResponse

    settings = get_settings()
    problems: list[str] = []
    if not settings.database_url:
        problems.append("database_url not configured")

    db_ok = False
    if not problems:
        try:
            from sqlalchemy import text

            engine = create_db_engine()
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("select 1"))
                db_ok = True
            finally:
                await engine.dispose()
        except Exception:
            problems.append("postgres unreachable")

    if problems:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "problems": problems},
        )
    return Response(
        content='{"status":"ok","checks":{"postgres":%s}}'
        % ("true" if db_ok else "false"),
        media_type="application/json",
    )


@router.get("/metrics")
async def prometheus_metrics() -> Response:
    return Response(content=metrics.render(), media_type="text/plain")


@router.post("/api/sessions")
async def create_session() -> dict[str, Any]:
    """创建游戏会话（占位，#5 接入 SessionApplication 后替换）。"""
    return {"session_id": "placeholder", "stage": "init"}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 占位端点：连接确认 + 回声（#5 接入命令协议后替换）。"""
    await ws.accept()
    metrics.set_gauge("wenjing_ws_connections", metrics.get("wenjing_ws_connections") + 1)
    try:
        await ws.send_json(
            {
                "type": "system",
                "id": 0,
                "session_id": "",
                "content": {"category": "info", "text": "connected"},
                "timestamp": time.time(),
            }
        )
        while True:
            data = await ws.receive_json()
            await ws.send_json({"type": "echo", "content": data})
    except Exception:
        pass
    finally:
        metrics.dec("wenjing_ws_connections")
        try:
            await ws.close()
        except Exception:
            pass
