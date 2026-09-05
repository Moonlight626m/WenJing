"""事件分支模型（issue #4 / spec 回溯决策）。

对应 `event_branches` 表：回溯不物理删除历史，而是创建/激活新分支；
每个会话有且只有一个活动分支（sessions.active_branch_id 指向）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class EventBranchRecord(Base):
    """一个事件分支：root_sequence 之前的历史继承自 parent 分支。"""

    __tablename__ = "event_branches"
    __table_args__ = (
        Index("idx_event_branches_session", "session_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    root_sequence: Mapped[int] = mapped_column(Integer, default=0)
    parent_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_by_command_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
