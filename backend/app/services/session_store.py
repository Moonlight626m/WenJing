"""SessionStore：剧情世界持久化深模块（恢复 + 单事务提交 + 回收）。

把「从 DB 重建运行时所需的数据」与「命令/系统事件单事务落库」从
`SessionApplication` 抽出，收敛原先重复两遍的乐观锁 CAS 拼写。调用方只需
`restore()` / `load_package()` / `commit()` / `discard()`，无需了解事件行、
head/branch、快照与冲突语义。

命令路径与 `initialize_session` 已走同一 `commit()`；ADR-0005 §5 的「命令之外的
事件路径」（`report_runtime_event` / `report_asset_ready`，M4 #55/#56）将直接复用
此接缝，无需另起 CAS 拼写。

事务边界（沿用 #21）：`commit()` 以 `UPDATE ... WHERE version = expected`
抢占会话行（兼作行锁），成功后再写事件/命令/head/快照；任何失败整事务回滚，
绝不部分推进。
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.commands import PlayerCommand
from app.contracts.script import ScriptPackage
from app.domain.game.event import GameEvent
from app.infrastructure.db.event_store import PersistentEventStore, branch_uuid
from app.infrastructure.errx import codes, new, wrap
from app.infrastructure.models.command import CommandRecord, CommandStatus
from app.infrastructure.models.event import EVENTS_SCHEMA_VERSION, GameEventRecord
from app.infrastructure.models.event_branch import EventBranchRecord
from app.infrastructure.models.script import Script as ScriptRecord
from app.infrastructure.models.session import Session as SessionRecord
from app.infrastructure.models.snapshot import Snapshot as SnapshotRecord

_UNSET: Any = object()


@dataclass
class LoadedSession:
    """`restore()` 的产物：重建运行时所需的一致快照（会话行加锁读）。"""

    session: SessionRecord
    package: ScriptPackage
    store: PersistentEventStore
    events: list[GameEvent]
    snapshot: SnapshotRecord | None
    version: int


class SessionStore:
    """会话持久化唯一入口（恢复/提交/回收）。"""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    # ===== 读取 =====

    async def has_command(self, command_id: uuid.UUID) -> bool:
        """幂等闸：命令是否已受理（commands 主键）。"""
        async with self._factory() as s:
            return await s.get(CommandRecord, command_id) is not None

    async def load_package(self, session_id: uuid.UUID) -> ScriptPackage | None:
        """只取会话引用的剧本包（状态查询/初始化用）；无生成内容返回 None。"""
        async with self._factory() as s:
            sess = await s.get(SessionRecord, session_id)
            script_id = sess.script_id if sess is not None else None
            row = (
                await s.get(ScriptRecord, script_id) if script_id is not None else None
            )
        if row is None or row.script_data is None:
            return None
        try:
            return ScriptPackage.model_validate(row.script_data)
        except Exception as exc:
            raise wrap(
                exc,
                codes.PER_INCOMPATIBLE_SCHEMA,
                extra={"id": str(session_id), "reason": "script package invalid"},
            ) from exc

    async def restore(self, session_id: uuid.UUID) -> LoadedSession:
        """锁定会话行，一致读取 (version, 剧本包, 快照, 事件流)。

        容错（issue #13）：剧本/快照损坏回退为明确错误由上层处理；事件损坏
        以 `PER_CORRUPT_SNAPSHOT` / `PER_WRITE_FAILED` 上抛。
        """
        async with self._factory() as s:
            sess = await s.get(SessionRecord, session_id, with_for_update=True)
            version = sess.version if sess is not None else 0
            script_id = sess.script_id if sess is not None else None
            script_row = (
                await s.get(ScriptRecord, script_id) if script_id is not None else None
            )
            if sess is None or script_row is None or script_row.script_data is None:
                raise new(
                    codes.SESS_NOT_FOUND,
                    extra={"id": str(session_id), "reason": "script not available"},
                )
            try:
                package = ScriptPackage.model_validate(script_row.script_data)
            except Exception as exc:
                raise wrap(
                    exc,
                    codes.PER_INCOMPATIBLE_SCHEMA,
                    extra={"id": str(session_id), "reason": "script package invalid"},
                ) from exc
            snap = (
                await s.execute(
                    select(SnapshotRecord)
                    .where(SnapshotRecord.session_id == session_id)
                    .order_by(SnapshotRecord.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            store = PersistentEventStore()
            try:
                events = await store.restore_active_branch(s, str(session_id))
            except SQLAlchemyError as exc:
                raise wrap(
                    exc, codes.PER_WRITE_FAILED, extra={"op": "restore_events"}
                ) from exc
            except ValueError as exc:
                raise wrap(
                    exc, codes.PER_CORRUPT_SNAPSHOT, extra={"reason": "events corrupt"}
                ) from exc
        return LoadedSession(
            session=sess,
            package=package,
            store=store,
            events=events,
            snapshot=snap,
            version=version,
        )

    # ===== 写入 =====

    async def commit(
        self,
        *,
        session_id: uuid.UUID,
        store: PersistentEventStore,
        stage: str,
        expected_version: int | None,
        op: str,
        command: PlayerCommand | None = None,
        player_role: str | None | object = _UNSET,
        ended: bool = False,
        runtime_state: Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        """事件 + 命令 + head/branch/stage/快照，同一事务。

        `expected_version=None` 表示以事务内读到的会话版本为基线（系统初始化）；
        传入恢复时读到的版本即为乐观锁 CAS（并发冲突 `SESS_CONFLICT`）。
        `player_role` 仅在显式传入时写入（`_UNSET` = 保持库中原值）。
        事件非空且给了 `runtime_state` 工厂时才追加快照行（无事件不计算导出）。
        """
        try:
            async with self._factory() as s:
                sess = await s.get(SessionRecord, session_id)
                if sess is None:
                    raise new(codes.SESS_NOT_FOUND, extra={"id": str(session_id)})
                expected = sess.version if expected_version is None else expected_version

                # 1) 乐观锁 CAS 抢占：版本不符即冲突，事务内不写任何东西
                claimed = await s.execute(
                    update(SessionRecord)
                    .where(
                        SessionRecord.id == session_id,
                        SessionRecord.version == expected,
                    )
                    .values(version=expected + 1)
                )
                if claimed.rowcount != 1:
                    raise new(
                        codes.SESS_CONFLICT,
                        extra={"id": str(session_id), "expected": expected},
                    )

                # 2) 持锁后写事件与命令（同事务；任何失败整体回滚）
                rows = await store.write_pending(s, str(session_id))
                if command is not None:
                    s.add(
                        CommandRecord(
                            command_id=command.command_id,
                            session_id=session_id,
                            kind=command.kind.value,
                            payload=command.payload,
                            status=CommandStatus.SUCCEEDED.value,
                        )
                    )
                await s.flush()
                head_db = rows[-1].id if rows else sess.head_event_id

                # 3) 更新 head/branch/stage/status（head 依赖新事件行，故在写入后）
                values: dict[str, Any] = {
                    "head_event_id": head_db,
                    "active_branch_id": branch_uuid(session_id, store.active_branch_id),
                    "current_stage": stage,
                    "status": "ended" if ended else sess.status,
                }
                if player_role is not _UNSET:
                    values["player_role"] = player_role
                await s.execute(
                    update(SessionRecord)
                    .where(SessionRecord.id == session_id)
                    .values(**values)
                )
                if rows and runtime_state is not None:
                    export = runtime_state()
                    s.add(
                        SnapshotRecord(
                            session_id=session_id,
                            event_id=head_db,
                            state_machine=json.dumps(
                                {
                                    "stage": export["stage"],
                                    "phase": export.get("phase"),
                                }
                            ),
                            character_memories=export.get("character_memories") or {},
                            plot_context=export,
                            schema_version=EVENTS_SCHEMA_VERSION,
                        )
                    )
                await s.commit()
        except Exception as exc:
            if isinstance(exc, SQLAlchemyError):
                raise wrap(exc, codes.PER_WRITE_FAILED, extra={"op": op}) from exc
            raise

    async def discard(self, session_id: uuid.UUID) -> None:
        """回收未成功初始化（或需删除）的会话：按 FK 顺序删净其数据。"""
        async with self._factory() as s:
            for model in (
                SnapshotRecord,
                CommandRecord,
                GameEventRecord,
                EventBranchRecord,
            ):
                await s.execute(delete(model).where(model.session_id == session_id))
            await s.execute(
                delete(SessionRecord).where(SessionRecord.id == session_id)
            )
            await s.commit()


__all__ = ["LoadedSession", "SessionStore"]
