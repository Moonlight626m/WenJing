"""事件溯源模型（issue #4 / design_04 §2.2）。

对应 `events` 表：事件只追加（append-only），payload 用 JSONB。
- `(branch_id, sequence)` 唯一：sequence 在分支内单调递增，是回放顺序的权威依据。
- causation_id / correlation_id 串联命令与事件的因果链（spec 决策）。
- schema_version 标记 payload 结构版本，供未来兼容迁移检测。
- `parent_id` 是旧引擎内存链的过渡字段，#7 重构后移除。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

EVENTS_SCHEMA_VERSION = "1.0.0"


class GameEventRecord(Base):
    """落库的游戏领域事件行。"""

    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("branch_id", "sequence", name="uq_events_branch_sequence"),
        Index("idx_events_session", "session_id", "id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("event_branches.id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    schema_version: Mapped[str] = mapped_column(
        Text, default=EVENTS_SCHEMA_VERSION
    )
    causation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 过渡字段：旧引擎的父事件链，command/step 重构后删除
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
