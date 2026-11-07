"""Checkpoint 快照模型（design_04 §3.2 / play-through-redesign §C1）。

对应 `snapshots` 表：每命令保存一次状态，加速恢复与回溯。
- `(branch_id, sequence)` 是快照的分支内坐标——回溯按「目标之前最近的存档点」
  恢复时靠它定位；`event_id` 仍保留为回溯截断的全局锚点。
- `label/kind` 是给人看的存档点标记（场景/回溯/命令）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.session import Base
from app.infrastructure.models._time import utcnow
from app.infrastructure.models.event import EVENTS_SCHEMA_VERSION


class Snapshot(Base):
    """一次回溯可用的状态快照（性能优化而非真相）。"""

    __tablename__ = "snapshots"
    __table_args__ = (
        Index("idx_snapshots_session", "session_id", "event_id"),
        Index(
            "ix_snapshots_session_branch_sequence",
            "session_id",
            "branch_id",
            "sequence",
        ),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id"), nullable=False
    )
    # 逻辑引用（无库级 FK，与 sessions.active_branch_id 同口径）：快照可能属于
    # 已被回溯放弃的分支，恢复时只挑活动路径上的坐标
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="command")
    state_machine: Mapped[str] = mapped_column(Text)

    character_memories: Mapped[dict] = mapped_column(JSONB, default=dict)
    plot_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    schema_version: Mapped[str] = mapped_column(
        Text, default=EVENTS_SCHEMA_VERSION
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
