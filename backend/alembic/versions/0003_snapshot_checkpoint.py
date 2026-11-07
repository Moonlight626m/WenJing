"""快照坐标与存档点标记（design play-through-redesign §C1，M8）

- `snapshots` 增 `branch_id/sequence/label/kind`：快照从「会话里最新一行」变成
  「(分支, 分支内序号) 上的一个存档点」，回溯可按目标前最近的存档点恢复。
- `sessions` 增 `head_sequence`：`head_event_id` 是全局行 id，`head_sequence`
  才是真正对外的「分支内进度序号」。

坐标口径（与 `active_events()` / WS `seq` / 回溯 `target_sequence` 一致）：
`sequence` 是事件在**该分支完整时间线**里的下标（含从父分支继承的前缀）。
注意它不等于 `events.sequence`——后者是分支自有行的序号，回溯出的子分支从 0
重新计数，所以回填要沿分支血缘把父分支前缀接上。

Revision ID: 0003_snapshot_checkpoint
Revises: 0002_session_ticks
Create Date: 2026-11-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003_snapshot_checkpoint"
down_revision: str | None = "0002_session_ticks"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _branch_paths(bind: sa.engine.Connection) -> dict[int, int]:
    """回填用：事件行 id → 它在自己分支时间线里的下标（含继承前缀）。

    数据量只有存量会话的事件行；血缘深度等于回溯次数，递归很浅。
    """
    branches = bind.execute(
        sa.text("select id, parent_branch_id, root_sequence from event_branches")
    ).all()
    own: dict[object, list[int]] = {}
    for event_id, branch_id in bind.execute(
        sa.text("select id, branch_id from events order by id")
    ).all():
        own.setdefault(branch_id, []).append(event_id)
    parent_of = {row[0]: row[1] for row in branches}
    root_seq = {row[0]: int(row[2] or 0) for row in branches}

    memo: dict[object, list[int]] = {}

    def path_of(branch: object) -> list[int]:
        if branch in memo:
            return memo[branch]
        own_ids = own.get(branch, [])
        parent = parent_of.get(branch)
        if parent is None or parent not in own:
            memo[branch] = own_ids
        else:
            parent_path = path_of(parent)
            # root_sequence 是父分支「自有事件」的下标，换算成父分支时间线下标
            prefix = len(parent_path) - len(own.get(parent, []))
            cut = prefix + root_seq.get(branch, 0) + 1
            memo[branch] = parent_path[:cut] + own_ids
        return memo[branch]

    sequence_of: dict[int, int] = {}
    for branch in list(parent_of):
        for index, event_id in enumerate(path_of(branch)):
            sequence_of[event_id] = index
    return sequence_of


def upgrade() -> None:
    # 1) 先在可空状态下补列 + 回填，再加 NOT NULL（存量行必须能从事件行推出坐标）
    op.add_column("snapshots", sa.Column("branch_id", sa.UUID(), nullable=True))
    op.add_column("snapshots", sa.Column("sequence", sa.BigInteger(), nullable=True))
    op.add_column("snapshots", sa.Column("label", sa.Text(), nullable=True))
    op.add_column(
        "snapshots",
        sa.Column(
            "kind", sa.String(length=32), nullable=False, server_default="command"
        ),
    )
    op.add_column(
        "sessions",
        sa.Column("head_sequence", sa.BigInteger(), nullable=False, server_default="0"),
    )

    bind = op.get_bind()
    sequence_of = _branch_paths(bind)
    for event_id, branch_id in bind.execute(
        sa.text(
            "select s.event_id, e.branch_id from snapshots s "
            "join events e on e.id = s.event_id"
        )
    ).all():
        bind.execute(
            sa.text(
                "update snapshots set branch_id = :branch, sequence = :sequence "
                "where event_id = :event_id"
            ),
            {
                "branch": branch_id,
                "sequence": sequence_of.get(event_id, 0),
                "event_id": event_id,
            },
        )
    for session_id, head_event_id in bind.execute(
        sa.text("select id, head_event_id from sessions where head_event_id is not null")
    ).all():
        bind.execute(
            sa.text("update sessions set head_sequence = :sequence where id = :id"),
            {"sequence": sequence_of.get(head_event_id, 0), "id": session_id},
        )

    op.alter_column("snapshots", "branch_id", nullable=False)
    op.alter_column("snapshots", "sequence", nullable=False)
    op.create_index(
        "ix_snapshots_session_branch_sequence",
        "snapshots",
        ["session_id", "branch_id", "sequence"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_snapshots_session_branch_sequence", table_name="snapshots")
    op.drop_column("sessions", "head_sequence")
    op.drop_column("snapshots", "kind")
    op.drop_column("snapshots", "label")
    op.drop_column("snapshots", "sequence")
    op.drop_column("snapshots", "branch_id")
