"""玩家命令模型（issue #4）。

对应 `commands` 表：command_id 是幂等键，重发命令不产生重复领域事件；
status 覆盖 received/succeeded/failed；result_event_id 指向命令产生的首条事件。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import BigInteger, DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


class CommandStatus(StrEnum):
    """命令生命周期状态。"""

    RECEIVED = "received"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class CommandRecord(Base):
    """一条玩家命令的持久化记录（幂等去重的权威依据）。"""

    __tablename__ = "commands"
    __table_args__ = {"extend_existing": True}

    command_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        Text, default=CommandStatus.RECEIVED.value
    )
    result_event_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
