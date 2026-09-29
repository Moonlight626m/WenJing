"""SessionApplication：游玩竖切的应用核心（issue #5；#19 起剧本由剧本库提供）。

职责与接缝：
- 生命周期：open_session(script_id) → submit_command → get_status；剧本由剧本库
  生成并发布，会话经 `script_id` 引用（生成/导入素材不在此，见 `app/services/script_library`）。
- 持久化（事务/CAS/恢复）委托 `app.services.session_store.SessionStore`：本类只做
  用例编排、访问控制与投影，不再直接拼事务。
- 幂等：commands 表主键为第一道闸（无内存运行时后仍是唯一权威闸）。
- 投影：StepResult/export_state → 契约 RuntimeUpdate/RuntimeState（projection.py）。
- **无状态命令路径（#21）**：不常驻内存运行时；每次命令从 DB（最新快照 + 事件）
  重建运行时（`SessionStore.restore` 以 `SELECT ... FOR UPDATE` 取一致快照）。
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.commands import CommandKind, PlayerCommand
from app.contracts.dto import (
    CreateSessionResponse,
    SessionListResponse,
    SessionStatusResponse,
    SessionSummary,
)
from app.contracts.runtime import RuntimeUpdate
from app.contracts.script import ScriptPackage
from app.domain.access import Actor, require_session_access, script_visible_to
from app.domain.game.engine_config import EngineConfig
from app.domain.game.game_runtime import GameRuntime
from app.domain.game.script_adapter import script_package_to_script
from app.domain.llm import LLMService
from app.infrastructure.db.event_store import PersistentEventStore, branch_uuid
from app.infrastructure.errx import codes, new
from app.infrastructure.models.event import EVENTS_SCHEMA_VERSION
from app.infrastructure.models.script import Script as ScriptRecord
from app.infrastructure.models.session import Session as SessionRecord
from app.services.session_projection import (
    messages_from_update,
    project_messages,
    project_state,
    project_status,
    project_update,
)
from app.services.session_store import SessionStore

logger = logging.getLogger("wenjing.session.application")


class SessionApplication:
    """会话应用服务：REST/WS 之下的唯一业务入口。"""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        agent_llm: LLMService,
        config: EngineConfig | None = None,
        usage_recorder=None,
        store: SessionStore | None = None,
    ) -> None:
        self._factory = session_factory
        self._agent_llm = agent_llm
        self._config = config or EngineConfig()
        self._usage_recorder = usage_recorder
        self._store = store or SessionStore(session_factory=session_factory)

    # ===== 创建 =====

    async def create_session(
        self,
        *,
        org_id: uuid.UUID,
        owner_user_id: uuid.UUID,
        script_id: int | None = None,
    ) -> CreateSessionResponse:
        """新建「剧情世界」，归属创建者并引用一个剧本（owner/org 由 Principal 带来）。"""
        sid = uuid.uuid4()
        async with self._factory() as s:
            s.add(
                SessionRecord(
                    id=sid,
                    org_id=org_id,
                    owner_user_id=owner_user_id,
                    script_id=script_id,
                )
            )
            await s.commit()
        return CreateSessionResponse(session_id=sid, created_at=datetime.now(UTC))

    async def open_session(
        self, *, actor: Actor, script_id: int
    ) -> SessionStatusResponse:
        """从可见剧本开局（#21）：校验可见性 → 建会话 → 初始化运行时 → 返回状态。

        可见性：owner 任意状态可玩；他人仅 `published` 且（`org` 同 org / `public` 跨 org）。
        初始化失败即回收刚建的会话行，绝不在「我的游戏」留下不可玩的 init 空壳。
        """
        await self._require_playable_script(actor, script_id)
        created = await self.create_session(
            org_id=actor.org_id, owner_user_id=actor.user_id, script_id=script_id
        )
        try:
            await self.initialize_session(created.session_id, actor)
        except Exception:
            await self._store.discard(created.session_id)
            raise
        return await self.get_status(created.session_id, actor=actor)

    async def list_my_sessions(self, actor: Actor) -> SessionListResponse:
        """「我的游戏」（#21）：当前用户自己的剧情世界，按最近更新倒序。"""
        async with self._factory() as s:
            rows = (
                await s.execute(
                    select(SessionRecord, ScriptRecord.name)
                    .outerjoin(
                        ScriptRecord, SessionRecord.script_id == ScriptRecord.id
                    )
                    .where(SessionRecord.owner_user_id == actor.user_id)
                    .order_by(SessionRecord.updated_at.desc())
                )
            ).all()
        return SessionListResponse(
            items=[
                SessionSummary(
                    session_id=sess.id,
                    script_id=sess.script_id,
                    script_name=name,
                    stage=sess.current_stage,
                    status=sess.status,
                    player_role=sess.player_role,
                    created_at=sess.created_at,
                    updated_at=sess.updated_at,
                )
                for sess, name in rows
            ]
        )

    async def _require_playable_script(self, actor: Actor, script_id: int) -> None:
        """不可见剧本按不存在处理（不泄露存在性）；无生成内容则 SCR_NOT_READY。"""
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
        if row is None or not script_visible_to(actor, row):
            raise new(codes.SCR_NOT_FOUND, extra={"id": script_id})
        if row.script_data is None:
            raise new(codes.SCR_NOT_READY, extra={"id": script_id})

    async def _access_session(
        self, session_id: uuid.UUID, actor: Actor
    ) -> SessionRecord:
        """加载会话并校验访问权：不存在 404，非 owner 403。"""
        async with self._factory() as s:
            sess = await s.get(SessionRecord, session_id)
        if sess is None:
            raise new(codes.SESS_NOT_FOUND, extra={"id": str(session_id)})
        require_session_access(actor, sess)
        return sess

    async def initialize_session(self, session_id: uuid.UUID, actor: Actor) -> None:
        """从会话引用的剧本初始化运行时：stage1_complete + 开场事件落库。

        无状态：运行时构建后即丢弃（#21），后续命令一律从 DB 重建。
        """
        sess = await self._access_session(session_id, actor)
        package = await self._store.load_package(session_id)
        if package is None:
            raise new(
                codes.SESS_NOT_FOUND,
                extra={"id": str(session_id), "reason": "script not generated"},
            )
        runtime, store = self._build_runtime(
            session_id,
            package,
            usage_context=self._usage_context(session_id, sess),
        )
        await runtime.start()
        await self._commit_system_events(
            session_id, store, stage=runtime.state.stage
        )

    # ===== 命令受理（幂等 + 单事务持久化 + 无状态重建）=====

    async def submit_command(
        self, session_id: uuid.UUID, command: PlayerCommand, *, actor: Actor
    ) -> RuntimeUpdate:
        update_result, _store = await self._submit(session_id, command, actor=actor)
        return update_result

    async def submit_command_messages(
        self, session_id: uuid.UUID, command: PlayerCommand, *, actor: Actor
    ) -> list[dict]:
        """WS 用：一次提交同时返回投影更新与本次应发布的消息（复用同一 store）。"""
        update_result, store = await self._submit(session_id, command, actor=actor)
        return messages_from_update(session_id, store, update_result)

    async def _submit(
        self, session_id: uuid.UUID, command: PlayerCommand, *, actor: Actor
    ) -> tuple[RuntimeUpdate, PersistentEventStore]:
        await self._access_session(session_id, actor)
        runtime, store, version = await self._restore_runtime(session_id)

        if await self._store.has_command(command.command_id):
            # 幂等闸：对账返回当前状态，不重复执行
            return (
                project_update(
                    session_id, store, self._idle_result(runtime, duplicate=True)
                ),
                store,
            )

        # 终局闸：已结束的会话不再受理玩家命令（SESSION_ENDED 语义域）
        if runtime.state.ended:
            raise new(codes.SESS_ENDED, extra={"id": str(session_id)})

        payload = self._engine_payload(command, store)
        result = await runtime.submit(
            command_id=str(command.command_id),
            kind=command.kind.value,
            payload=payload,
        )
        await self._persist_command(
            session_id,
            command,
            store,
            runtime,
            result,
            expected_version=version,
        )
        return project_update(session_id, store, result), store

    async def _persist_command(
        self,
        session_id: uuid.UUID,
        command: PlayerCommand,
        store: PersistentEventStore,
        runtime: GameRuntime,
        result: Any = None,
        *,
        expected_version: int,
    ) -> None:
        """命令 + 事件 + head/version/active_branch + 快照，同一事务（见 SessionStore）。"""
        await self._store.commit(
            session_id=session_id,
            store=store,
            stage=runtime.state.stage,
            expected_version=expected_version,
            op="persist_command",
            command=command,
            player_role=runtime.state.player_role,
            ended=bool(result.terminal) if result is not None else False,
            runtime_state=runtime.export_state,
        )

    async def _commit_system_events(
        self, session_id: uuid.UUID, store: PersistentEventStore, *, stage: str
    ) -> None:
        """系统动作（如 runtime.start）产生的事件 + head/stage 推进，单事务。"""
        await self._store.commit(
            session_id=session_id,
            store=store,
            stage=stage,
            expected_version=None,
            op="commit_system_events",
        )

    # ===== 状态查询 =====

    async def get_status(
        self, session_id: uuid.UUID, *, actor: Actor
    ) -> SessionStatusResponse:
        sess = await self._access_session(session_id, actor)
        pkg = await self._store.load_package(session_id)
        playable = (
            [c.name for c in pkg.characters if c.is_player_playable] if pkg else []
        )
        return project_status(
            session_id=session_id,
            stage=sess.current_stage,
            active_branch_id=sess.active_branch_id
            or branch_uuid(session_id, 1),
            head_event_id=sess.head_event_id,
            playable_roles=playable,
            selected_role=sess.player_role,
        )

    # ===== WS 会话协议支撑（session_init 重建 / 断线补发）=====

    async def session_init(self, session_id: uuid.UUID, *, actor: Actor) -> dict:
        """连接建立/重连时的权威快照：阶段、历史、交互点（运行时按需从 DB 重建）。"""
        await self._access_session(session_id, actor)
        runtime, store, _ = await self._restore_runtime(session_id)
        state = project_state(session_id, store, runtime.export_state())
        return {
            "session_id": str(session_id),
            "stage": state.stage.value,
            "branch_id": str(state.branch_id),
            "last_sequence": state.last_sequence,
            "plot_log": state.plot_context.get("plot_log", []),
            "player_role": state.plot_context.get("player_role"),
            # 场景切换背景（#53）：稳定引用 + 键 + 标题，前端据此签 URL / 判淡入
            "scene_key": state.scene_key,
            "scene_title": state.scene_title,
            "current_asset": (
                state.current_asset.model_dump(mode="json")
                if state.current_asset is not None
                else None
            ),
            "active_interaction": (
                state.active_interaction.model_dump(mode="json")
                if state.active_interaction is not None
                else None
            ),
            "allowed_commands": [k.value for k in state.allowed_commands()],
        }

    async def replay_after(
        self, session_id: uuid.UUID, after_seq: int, *, actor: Actor
    ) -> list[dict]:
        """按 last_confirmed_seq 补发：从 DB 活动分支重建消息序列。"""
        await self._access_session(session_id, actor)
        runtime, store, _ = await self._restore_runtime(session_id)
        state = project_state(session_id, store, runtime.export_state())
        return project_messages(
            session_id,
            store,
            after_seq=after_seq,
            interaction=state.active_interaction,
            allowed_commands=[k.value for k in state.allowed_commands()],
        )

    # ===== 恢复（断线重连 / 进程重启 / 每命令）=====

    async def _restore_runtime(
        self, session_id: uuid.UUID
    ) -> tuple[GameRuntime, PersistentEventStore, int]:
        """从 DB 重建运行时：剧本 + 分支结构 + 事件流 + 最新快照重放。

        无状态（#21）：每次命令都走此路径，返回 (runtime, store, 恢复时会话版本)；
        版本用于命令落库的乐观锁 CAS（见 `_persist_command`）。

        一致性：以 `SELECT ... FOR UPDATE` 锁定会话行，使读到的 (version, events)
        来自同一一致快照（不持锁做 LLM）。

        容错（issue #13）：剧本/快照损坏或 schema 不兼容时，宁可忽略快照
        从完整事件流重建，也不让恢复路径崩溃；剧本无法解析则返回明确错误。
        """
        loaded = await self._store.restore(session_id)
        runtime, store = self._build_runtime(
            session_id,
            loaded.package,
            store=loaded.store,
            usage_context=self._usage_context(session_id, loaded.session),
        )
        snap = loaded.snapshot
        base: dict | None = None
        if snap is not None:
            if snap.schema_version != EVENTS_SCHEMA_VERSION:
                logger.warning(
                    "snapshot_schema_incompatible",
                    extra={
                        "session_id": str(session_id),
                        "found": snap.schema_version,
                        "expected": EVENTS_SCHEMA_VERSION,
                    },
                )
            elif isinstance(snap.plot_context, dict):
                base = snap.plot_context
            else:
                logger.warning(
                    "snapshot_payload_corrupt",
                    extra={"session_id": str(session_id)},
                )
        cutoff = int((base or {}).get("latest_event_id", 0))
        replay = [e.to_dict() for e in loaded.events if e.event_id > cutoff]
        try:
            runtime.replay_from(base, replay)
        except Exception as exc:
            logger.warning(
                "snapshot_replay_failed_rebuild",
                extra={"session_id": str(session_id), "reason": str(exc)},
            )
            runtime.replay_from(None, [e.to_dict() for e in loaded.events])

        return runtime, store, loaded.version

    # ===== 内部工具 =====

    def _build_runtime(
        self,
        session_id: uuid.UUID,
        package: ScriptPackage,
        *,
        store: PersistentEventStore | None = None,
        usage_context=None,
    ) -> tuple[GameRuntime, PersistentEventStore]:
        store = store or PersistentEventStore()
        llm = self._agent_llm
        if self._usage_recorder is not None and usage_context is not None:
            llm = self._usage_recorder.wrap(self._agent_llm, usage_context)
        runtime = GameRuntime(
            session_id=str(session_id),
            script=script_package_to_script(package),
            llm=llm,
            config=self._config,
            event_store=store,
        )
        return runtime, store

    def _usage_context(self, session_id: uuid.UUID, sess: SessionRecord):
        """构造该会话的 LLM 用量归属上下文（无 recorder 时返回 None）。"""
        if self._usage_recorder is None:
            return None
        from app.infrastructure.usage import UsageContext

        return UsageContext(
            org_id=sess.org_id,
            user_id=sess.owner_user_id,
            script_id=sess.script_id,
            session_id=session_id,
        )

    @staticmethod
    def _engine_payload(
        command: PlayerCommand, store: PersistentEventStore
    ) -> dict:
        """契约 payload → 引擎 payload；回溯以活动分支 sequence 定位本地事件。"""
        p = command.payload_model
        kind = command.kind
        if kind is CommandKind.SELECT_ROLE:
            return {"role_name": p.role_name}
        if kind is CommandKind.CHOOSE_OPTION:
            return {"option_id": p.option_id}
        if kind is CommandKind.FREE_INPUT:
            return {"text": p.text}
        if kind is CommandKind.ROLLBACK_TO_EVENT:
            path = store.active_events()
            if p.target_sequence >= len(path):
                raise new(
                    codes.ENG_ROLLBACK_TARGET_MISSING,
                    extra={"event_id": p.target_sequence},
                )
            return {"target_event_id": path[p.target_sequence].event_id}
        return {}

    @staticmethod
    def _idle_result(runtime: GameRuntime, *, duplicate: bool):
        from app.domain.game.game_runtime import StepResult

        return StepResult(
            state=runtime.export_state(),
            new_events=[],
            active_interaction=(
                {
                    "mode": runtime.active_interaction.mode,
                    "context": runtime.active_interaction.context,
                    "options": [dict(o) for o in runtime.active_interaction.options],
                    "hint": runtime.active_interaction.hint,
                }
                if runtime.active_interaction is not None
                else None
            ),
            allowed_commands=[],
            duplicate=duplicate,
        )


__all__ = ["SessionApplication"]
