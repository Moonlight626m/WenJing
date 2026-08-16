import time
from typing import Any

from fastapi import APIRouter, WebSocket

from app.schemas.messages import SystemMessage

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, Any]:
    """健康检查。骨架阶段不依赖 DB。"""
    return {"status": "ok"}


@router.post("/api/sessions")
async def create_session() -> dict[str, Any]:
    """创建游戏会话（占位）。骨架阶段返回占位 session_id。"""
    return {"session_id": "placeholder", "stage": "init"}


@router.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """WebSocket 占位端点：连接确认 + 回声。"""
    await ws.accept()
    await ws.send_json(
        SystemMessage(
            id=0,
            session_id="",
            content={"category": "info", "text": "connected"},
            timestamp=time.time(),
        ).model_dump()
    )
    try:
        while True:
            data = await ws.receive_json()
            await ws.send_json({"type": "echo", "content": data})
    except Exception:
        await ws.close()
