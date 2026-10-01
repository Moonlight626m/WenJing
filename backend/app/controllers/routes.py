"""路由层：轻薄协议 adapter（issue #3 诊断端点；#5 竖切会话端点）。

业务全部委托 `SessionApplication`；本层只做协议转换与错误 envelope 映射。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Response, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

import app.infrastructure.models  # noqa: F401  # 确保 ORM 元数据注册
from app.composition import get_container
from app.contracts.dto import (
    CreateSessionRequest,
    SessionListResponse,
    SessionStatusResponse,
)
from app.controllers.auth_deps import Principal, get_principal, require_csrf, resolve_principal
from app.controllers.errors import error_response as _error_response
from app.domain.game.streaming import StreamTee
from app.infrastructure.config import get_settings
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.db.session import create_engine as create_db_engine
from app.infrastructure.diagnostics.metrics import metrics
from app.infrastructure.errx import Error as WJError
from app.infrastructure.errx import codes, new
from app.services.audio_channel import AudioTrackChannel
from app.services.stream_channel import StreamChannel

router = APIRouter()

logger = logging.getLogger("wenjing.api.routes")


def get_application():
    """进程级 SessionApplication（由组合根 `app.composition` 装配）。"""
    return get_container().session_application


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
    """提交 PlayerCommand（#5）：幂等 + 单事务持久化 → RuntimeUpdate 投影。

    `PlayerCommand` 的校验失败**必须**转成业务信封（#66）：这是契约里明写的唯一
    游戏输入入口，非法请求体是常规客户端错误，不是服务端故障。裸 `ValidationError`
    会被 Starlette 兜成 500 + 纯文本，前端拿不到 `code` 也就无法提示。
    WS 路径早就这么处理了（`_handle` 里的 `client_message_adapter`），这里补齐。
    """
    from app.contracts.commands import PlayerCommand

    try:
        try:
            command = PlayerCommand.model_validate(body)
        except ValidationError as exc:
            raise new(
                codes.PRT_MALFORMED_MESSAGE, extra={"reason": str(exc)[:120]}
            ) from exc
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

    - seq = 活动分支路径序号；消息仅在事务提交后发布；
    - confirm_messages(last_confirmed_seq) 修剪本连接 outbox；
    - resync_request(last_confirmed_seq) 优先重发本连接 outbox 缺口，
      跨连接（重连）时经 SessionApplication.replay_after 从 DB 重建。
    - **命令外事件**（#56 运行期配图就绪）不经本连接发起，改由
      `SessionEventHub` 投递到本连接的队列：循环因此同时等「客户端消息」与
      「推送消息」两件事，否则等 receive 的协程会把推送一直压在队列里。
    """
    from app.contracts.dto import client_message_adapter
    from app.infrastructure.diagnostics.errors import envelope_for

    await ws.accept()
    metrics.set_gauge("wenjing_ws_connections", metrics.get("wenjing_ws_connections") + 1)
    application = get_application()
    container = get_container()
    hub = container.event_hub
    outbox: list[dict[str, Any]] = []
    # 音轨出口是**连接级**的（ADR-0005 §11）：一条连接的音频只发给这条连接，
    # `cancel_audio` 也只可能取消自己听得到的轨。在 `try` **之前**建，是为了让
    # `finally` 里的 `aclose` 在鉴权/参数校验提前失败时也有对象可关。
    audio = AudioTrackChannel(session_id, ws.send_json, ws.send_bytes)

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

    async def _handle(data: Any) -> None:
        """处理一条客户端消息；发出的消息同步进 outbox（补发协议依赖它）。"""
        try:
            parsed = client_message_adapter.validate_python(data)
        except Exception as exc:
            await _send_error(
                new(codes.PRT_MALFORMED_MESSAGE, extra={"reason": str(exc)[:120]})
            )
            return

        if parsed.type == "submit_command":
            command = parsed.command
            if str(command.session_id) != session_id:
                await _send_error(
                    new(
                        codes.PRT_MALFORMED_MESSAGE,
                        extra={"reason": "command.session_id mismatch"},
                    )
                )
                return
            # 瞬态流式字幕出口（#60）：per-connection，只在本次命令内有效。
            # 它发的 `stream_*` 不进 outbox——没有 seq 就没有缺口，重连补发靠的是
            # 事件流里那条完整的 `character_speech`。
            channel = StreamChannel(session_id, ws.send_json)
            # tee（#62）：文字逐段给 WS，同时攒成整句喂 TTS 出口（#63）。
            # 运行时只认 `speech_sink` 一个出口，怎么分流是这里的事。
            synthesizer = container.tts_synthesizer_factory(
                audio,
                session_id=sid,
                org_id=actor.org_id,
                user_id=actor.user_id,
                script_id=script_id,
            )
            tee = StreamTee(text_sink=channel, sentence_sink=synthesizer)
            try:
                msgs = await application.submit_command_messages(
                    sid, command, actor=actor, speech_sink=tee
                )
            except WJError as exc:
                # 先收流再报错：错误消息不能被还没冲刷完的字幕挤到后面
                await synthesizer.aclose()
                await channel.aclose()
                await audio.flush()
                await _send_error(exc)
                return
            # 顺序：先等合成收尾（它还在往 audio 里塞帧），再冲刷两个出口。
            # 注意 audio 只 `flush` 不 `aclose`：它是**连接级**的，每条命令都关掉
            # 会让第二条命令起的音频全被静默吞掉（只有第一个角色有声音）。
            await synthesizer.aclose()
            await channel.aclose()
            await audio.flush()
            for msg in msgs:
                outbox.append(msg)
                await ws.send_json(msg)
        elif parsed.type == "cancel_audio":
            # barge-in（ADR-0005 §11）：客户端停播 + 服务端放掉这条音轨的待发数据。
            # 这里尤其**不能**顺手去打断命令：命令串行 + 事件同事务持久化是引擎的
            # 地基，服务端在生成中本就收不到新命令，barge-in 只可能是客户端行为。
            # 已经写进 socket 的字节收不回来，真正的"停"是客户端 `<audio>.pause()`。
            cancelled = audio.cancel(parsed.track_id)
            logger.info(
                "audio_cancel",
                extra={
                    "session_id": session_id,
                    "wj_extra": {
                        "track_id": parsed.track_id,
                        "cancelled": cancelled,
                    },
                },
            )
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

    try:
        if not _origin_allowed(ws):
            raise new(codes.AUTH_FORBIDDEN, extra={"reason": "origin not allowed"})
        async with SessionLocal() as db:
            principal, _ = await resolve_principal(ws.cookies, db)
        actor = principal.actor
        sid = _ensure_uuid(session_id)

        # 订阅先于 session_init：配图就绪是异步来的，晚订阅一秒就少一次即时换图
        # （漏掉的也能靠随后的 resync_request 从事件流补回来，但没必要漏）。
        with hub.subscribe(sid) as pushed:
            init = await application.session_init(sid, actor=actor)
            script_id = init.get("script_id")
            init_msg = {
                "type": "session_init",
                "seq": init["last_sequence"],
                "session_id": session_id,
                "payload": init,
            }
            outbox.append(init_msg)
            await ws.send_json(init_msg)

            # 两个任务常驻跨轮：等客户端消息的协程被取消会丢掉半条在途帧，
            # 所以只在它真的完成后重建（`pending_*` 为 None 时才重建）。
            pending_recv: asyncio.Task | None = None
            pending_push: asyncio.Task | None = None
            try:
                while True:
                    if pending_recv is None:
                        pending_recv = asyncio.create_task(ws.receive_json())
                    if pending_push is None:
                        pending_push = asyncio.create_task(pushed.get())
                    done, _ = await asyncio.wait(
                        {pending_recv, pending_push},
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if pending_push in done:
                        pushed_msg = pending_push.result()
                        pending_push = None
                        outbox.append(pushed_msg)
                        await ws.send_json(pushed_msg)
                    if pending_recv in done:
                        data = pending_recv.result()
                        pending_recv = None
                        await _handle(data)
            finally:
                for task in (pending_recv, pending_push):
                    if task is not None:
                        task.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    except WJError as exc:
        try:
            await _send_error(exc)
        except Exception:
            pass
    finally:
        # 音轨出口是连接级的：连接真的结束了才关（见上面 per-command 的 `flush`）。
        await audio.aclose()
        metrics.dec("wenjing_ws_connections")
        try:
            await ws.close()
        except Exception:
            pass
