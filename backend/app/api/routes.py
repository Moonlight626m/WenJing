"""路由层：轻薄协议 adapter（issue #3 诊断端点；#5 竖切会话端点）。

业务全部委托 `SessionApplication`；本层只做协议转换与错误 envelope 映射。
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Response, WebSocket, WebSocketDisconnect

import app.models  # noqa: F401  # 确保 ORM 元数据注册
from app.api.errors import error_response as _error_response
from app.config import get_settings
from app.db.session import create_engine as create_db_engine
from app.diagnostics.metrics import metrics
from app.errx import Error as WJError
from app.errx import codes, new

router = APIRouter()

_application = None


def get_application():
    """进程级 SessionApplication 单例。

    #12 真实集成组装：配置 LLM key 时 agent/script 共用同一 provider
    （DeepSeek/OpenAI…），RAG 走安全抓取（无搜索 provider 时降级为纯原文）；
    无 key 回落 DeterministicAgentLLM + 确定性合成（快速演示模式）。
    """
    global _application
    if _application is None:
        from app.agents.fake_llm import DeterministicAgentLLM
        from app.db.session import SessionLocal
        from app.rag.service import RagService
        from app.session.application import SessionApplication

        settings = get_settings()
        agent_llm: object = DeterministicAgentLLM()
        script_llm = None
        if settings.llm_api_key:
            try:
                from app.agents.model_config import ModelServiceFactory

                agent_llm = ModelServiceFactory.build(settings.llm_model_config())
                script_llm = agent_llm
            except Exception:
                agent_llm = DeterministicAgentLLM()
        _application = SessionApplication(
            session_factory=SessionLocal,
            agent_llm=agent_llm,
            script_llm=script_llm,
            rag=RagService(),
            model_name=settings.llm_model,
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


@router.get("/api/sessions/{session_id}")
async def session_status(session_id: str) -> dict[str, Any]:
    """会话状态查询（#5）：stage/分支/head/可扮演角色/生成进度。"""
    try:
        resp = await get_application().get_status(_ensure_uuid(session_id))
    except WJError as exc:
        return _error_response(exc)
    return resp.model_dump(mode="json")


@router.post("/api/sessions/{session_id}/material")
async def import_material(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """导入课文材料（#5）：走真实 ingestion 校验 + 原文分析。"""
    from app.contracts.material import MaterialInput

    try:
        inp = MaterialInput.model_validate(body)
        analysis = await get_application().import_material(
            _ensure_uuid(session_id), inp
        )
    except WJError as exc:
        return _error_response(exc)
    return analysis.model_dump(mode="json")


@router.post("/api/sessions/{session_id}/generate")
async def generate_script(session_id: str) -> dict[str, Any]:
    """Stage1 生成（#5 fake-backed）：产出合法 ScriptPackage。"""
    try:
        pkg = await get_application().generate_script(_ensure_uuid(session_id))
    except WJError as exc:
        return _error_response(exc)
    return pkg.model_dump(mode="json")


@router.post("/api/sessions/{session_id}/commands")
async def submit_command(session_id: str, body: dict[str, Any]) -> dict[str, Any]:
    """提交 PlayerCommand（#5）：幂等 + 单事务持久化 → RuntimeUpdate 投影。"""
    from app.contracts.commands import PlayerCommand

    try:
        command = PlayerCommand.model_validate(body)
        update = await get_application().submit_command(
            _ensure_uuid(session_id), command
        )
    except WJError as exc:
        return _error_response(exc)
    return update.model_dump(mode="json")


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
            sid = _ensure_uuid(session_id)
            init = await application.session_init(sid)
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
                    update = await application.submit_command(sid, command)
                except WJError as exc:
                    await _send_error(exc)
                    continue
                from app.session.projection import messages_from_update

                runtime, store = await application._ensure_runtime(sid)
                for msg in messages_from_update(sid, store, update):
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
                    replay = await application.replay_after(sid, last)
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
