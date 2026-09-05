"""分支回溯的原子持久化（issue #8 验收标准 5/6）。

一次回溯落库 = 新建 `event_branches` 行 + 可选 `snapshots` 行 + 推进
`sessions.active_branch_id / head_event_id / version`，三者同一事务提交：
- 乐观锁（`version = expected_version`）守卫每会话单命令并发；
- 失败（版本冲突）时整事务回滚，不留下半条分支/快照/head 状态。
"""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event import EVENTS_SCHEMA_VERSION
from app.models.event_branch import EventBranchRecord
from app.models.session import Session
from app.models.snapshot import Snapshot


async def commit_rollback_branch(
    session: AsyncSession,
    *,
    session_id: uuid.UUID,
    parent_branch_id: uuid.UUID,
    root_sequence: int,
    head_event_id: int,
    expected_version: int,
    created_by_command_id: uuid.UUID | None = None,
    snapshot: dict | None = None,
    new_branch_id: uuid.UUID | None = None,
) -> uuid.UUID:
    """同一事务内创建新分支并切换活动分支 + 推进 head/version。

    - 新分支 `parent_branch_id` 指向旧活动分支，`root_sequence` 为回溯目标序列；
      历史（root_sequence 之前的事件）由父分支继承，不物理复制。
    - `new_branch_id` 缺省时随机生成；接入确定性映射时可传
      `branch_uuid(session_id, store.active_branch_id)` 与内存分支对齐。
    - `snapshot` 非空时同批写入 `snapshots` 表（快照与分支/head 原子提交）。
    - 乐观锁版本不匹配 → 抛出异常且不提交（调用方事务边界回滚）。
    返回新分支 id。
    """
    if new_branch_id is None:
        new_branch_id = uuid.uuid4()
    session.add(
        EventBranchRecord(
            id=new_branch_id,
            session_id=session_id,
            root_sequence=root_sequence,
            parent_branch_id=parent_branch_id,
            created_by_command_id=created_by_command_id,
        )
    )
    if snapshot is not None:
        session.add(
            Snapshot(
                session_id=session_id,
                event_id=head_event_id,
                state_machine=snapshot.get("state_machine", ""),
                character_memories=snapshot.get("character_memories", {}),
                plot_context=snapshot.get("plot_context"),
                event_count=int(snapshot.get("event_count", 0)),
                schema_version=EVENTS_SCHEMA_VERSION,
            )
        )
    # asyncpg 不允许同一连接并发执行：先 flush 待插入行，再执行 UPDATE
    await session.flush()
    result = await session.execute(
        update(Session)
        .where(Session.id == session_id, Session.version == expected_version)
        .values(
            active_branch_id=new_branch_id,
            head_event_id=head_event_id,
            version=Session.version + 1,
        )
    )
    if result.rowcount != 1:
        raise RuntimeError(
            f"乐观锁版本冲突：session={session_id} expected_version={expected_version}"
        )
    await session.commit()
    return new_branch_id
