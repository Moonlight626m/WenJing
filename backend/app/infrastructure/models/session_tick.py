"""离线 tick 台账（design play-through-redesign §B6，里程碑 M7）。

对应 `session_ticks` 表：`(session_id, tick_index)` 唯一键即 **claim-first** 的幂等闸
——同一 tick 无论重连多少次、多少个进程同时补算，只有一个能插入成功并执行。
`tick_index` 从 1 递增；`tick_id = uuid5(session_id, tick_index)` 见
`domain/game/offline_ticks.py`。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.session import Base
from app.infrastructure.models._time import utcnow


class SessionTick(Base):
    """一次离线 tick 的认领记录（存在即「已执行/已认领」）。"""

    __tablename__ = "session_ticks"
    __table_args__ = ({"extend_existing": True},)

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("sessions.id", ondelete="CASCADE"),
        primary_key=True,
    )
    tick_index: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
