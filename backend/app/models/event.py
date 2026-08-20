"""事件溯源模型（design_04 §2.2）。

对应 `events` 表：事件只追加（append-only），payload 用 JSONB。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class GameEventRecord(Base):
    """落库的游戏事件行，与内存 `EventStore` 的 `GameEvent` 一一对应。"""

    __tablename__ = "events"
    __table_args__ = (
        Index("idx_events_session", "session_id", "id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    parent_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("events.id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
