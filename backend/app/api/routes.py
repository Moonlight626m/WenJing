"""路由层：轻薄协议 adapter（issue #3 诊断端点；#5 竖切会话端点）。

业务全部委托 `SessionApplication`；本层只做协议转换与错误 envelope 映射。
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect

import app.models  # noqa: F401  # 确保 ORM 元数据注册
from app.api.errors import error_response as _error_response
from app.auth.deps import Principal, get_principal, require_csrf, resolve_principal
from app.config import get_settings
from app.contracts.dto import (
    CreateSessionRequest,
    SessionListResponse,
    SessionStatusResponse,
)
from app.db.session import SessionLocal
from app.db.session import create_engine as create_db_engine
from app.diagnostics.metrics import metrics
from app.errx import Error as WJError
from app.errx import codes, new

router = APIRouter()

_application = None


def get_application():
    """进程级 SessionApplication 单例。

    #12 真实集成组装：配置 LLM key 时用真实 provider（DeepSeek/OpenAI…）；
    无 key 回落 DeterministicAgentLLM（快速演示/测试模式）。
    剧本生成/素材导入在 `app/api/scripts.py` 的 ScriptLibrary 中组装。
    """
    global _application
    if _application is None:
        from app.agents.fake_llm import DeterministicAgentLLM
        from app.db.session import SessionLocal
        from app.session.application import SessionApplication
        from app.usage import UsageRecorder

        settings = get_settings()
        agent_llm: object = DeterministicAgentLLM()
        if settings.llm_api_key:
            try:
                from app.agents.model_config import ModelServiceFactory

                agent_llm = ModelServiceFactory.build(settings.llm_model_config())
            except Exception:
                agent_llm = DeterministicAgentLLM()
        _application = SessionApplication(
            session_factory=SessionLocal,
            agent_llm=agent_llm,
            usage_recorder=UsageRecorder(session_factory=SessionLocal),
        )
    return _application


def _ensure_uuid(raw: str) -> uuid.UUID:
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise new(codes.PRT_MALFORMED_MESSAGE, extra={"reason": "invalid uuid"}) from exc


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


@router.post("/api/sessions", status_code=201, response_model=SessionStatusResponse)
async def create_session(
    body: CreateSessionRequest,
    principal: Annotated[Principal, Depends(require_csrf)],
) -> SessionStatusResponse:
    """从可见剧本开局（#21）：建会话并初始化运行时，直接返回状态（含可扮演角色）。"""
    try:
        return await get_application().open_session(
            actor=principal.actor, script_id=body.script_id
        )
    except WJError as exc:
        return _error_response(exc)


@router.get("/api/sessions", response_model=SessionListResponse)
async def list_sessions(
    principal: Annotated[Principal, Depends(get_principal)],
) -> SessionListResponse:
    """我的游戏（#21）：当前用户自己的剧情世界列表，按最近更新倒序。"""
    try:
        return await get_application().list_my_sessions(principal.actor)
    except WJError as exc:
        return _error_response(exc)


@router.get("/api/sessions/{session_id}")
async def session_status(
    session_id: str,
    principal: Annotated[Principal, Depends(get_principal)],
) -> dict[str, Any]:
    """会话状态查询（#5）：stage/分支/head/可扮演角色。"""
    try:
        resp = await get_application().get_status(
            _ensure_uuid(session_id), actor=principal.actor
        )
    except WJError as exc:
        return _error_response(exc)
    return resp.model_dump(mode="json")


@router.post("/api/sessions/{session_id}/commands")
async def submit_command(
    session_id: str,
    body: dict[str, Any],
    principal: Annotated[Principal, Depends(require_csrf)],
) -> dict[str, Any]:
    """提交 PlayerCommand（#5）：幂等 + 单事务持久化 → RuntimeUpdate 投影。"""
    from app.contracts.commands import PlayerCommand

    try:
        command = PlayerCommand.model_validate(body)
        if str(command.session_id) != session_id:
            raise new(
                codes.PRT_MALFORMED_MESSAGE,
                extra={"reason": "command.session_id mismatch"},
            )
        update = await get_application().submit_command(
            _ensure_uuid(session_id), command, actor=principal.actor
        )
    except WJError as exc:
        return _error_response(exc)
    return update.model_dump(mode="json")


def _origin_allowed(ws: WebSocket) -> bool:
    """WS 握手 Origin 白名单校验（跨站 WS 的纵深防御）。

    浏览器跨站发起的 WS 必带 Origin，不在 CORS 白名单即拒；无 Origin 的
    非浏览器客户端放行（Cookie SameSite=Lax + 归属校验已是基线防护）。
    """
    origin = ws.headers.get("origin")
    if not origin:
        return True
    allowed = {
        o.strip() for o in get_settings().cors_origins.split(",") if o.strip()
    }
    return origin in allowed


@router.websocket("/ws/{session_id}")
async def session_ws(ws: WebSocket, session_id: str) -> None:
    """会话 WS（issue #5）：session_init 重建 + submit_command + confirm/resync 补发。

    - seq = 活动分支路径序号；消息仅在命令事务提交后发布；
    - confirm_messages(last_confirmed_seq) 修剪本连接 outbox；
    - resync_request(last_confirmed_seq) 优先重发本连接 outbox 缺口，
      跨连接（重连）时经 SessionApplication.replay_after 从 DB 重建。
    """
    from app.contracts.dto import client_message_adapter
    from app.diagnostics.errors import envelope_for

    await ws.accept()
    metrics.set_gauge("wenjing_ws_connections", metrics.get("wenjing_ws_connections") + 1)
    application = get_application()
    outbox: list[dict[str, Any]] = []

    async def _send_error(exc: WJError, seq: int = 0) -> None:
        env = envelope_for(exc)
        await ws.send_json(
            {
                "type": "error",
                "seq": seq,
                "session_id": session_id,
                "payload": {
                    "error_id": str(env.error_id),
                    "code": env.code,
                    "domain": env.domain.value,
                    "message": env.message,
                    "retryable": env.retryable,
                    "details": env.details,
                },
            }
        )

    try:
        try:
            if not _origin_allowed(ws):
                raise new(
                    codes.AUTH_FORBIDDEN, extra={"reason": "origin not allowed"}
                )
            async with SessionLocal() as db:
                principal, _ = await resolve_principal(ws.cookies, db)
            actor = principal.actor
            sid = _ensure_uuid(session_id)
            init = await application.session_init(sid, actor=actor)
        except WJError as exc:
            await _send_error(exc)
            await ws.close()
            return

        init_msg = {
            "type": "session_init",
            "seq": init["last_sequence"],
            "session_id": session_id,
            "payload": init,
        }
        outbox.append(init_msg)
        await ws.send_json(init_msg)

        while True:
            data = await ws.receive_json()
            try:
                parsed = client_message_adapter.validate_python(data)
            except Exception as exc:
                await _send_error(
                    new(codes.PRT_MALFORMED_MESSAGE, extra={"reason": str(exc)[:120]})
                )
                continue

            if parsed.type == "submit_command":
                command = parsed.command
                if str(command.session_id) != session_id:
                    await _send_error(
                        new(
                            codes.PRT_MALFORMED_MESSAGE,
                            extra={"reason": "command.session_id mismatch"},
                        )
                    )
                    continue
                try:
                    msgs = await application.submit_command_messages(
                        sid, command, actor=actor
                    )
                except WJError as exc:
                    await _send_error(exc)
                    continue
                for msg in msgs:
                    outbox.append(msg)
                    await ws.send_json(msg)
            elif parsed.type == "confirm_messages":
                last = parsed.last_confirmed_seq
                outbox[:] = [m for m in outbox if m["seq"] > last]
            elif parsed.type == "resync_request":
                last = parsed.last_confirmed_seq
                # session_init 是连接引导消息（每次连接都会重发），不参与补发
                replay = [
                    m for m in outbox if m["seq"] > last and m["type"] != "session_init"
                ]
                if not replay:
                    replay = await application.replay_after(sid, last, actor=actor)
                for msg in replay:
                    await ws.send_json(msg)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except WJError as exc:
        try:
            await _send_error(exc)
        except Exception:
            pass
    finally:
        metrics.dec("wenjing_ws_connections")
        try:
            await ws.close()
        except Exception:
            pass
