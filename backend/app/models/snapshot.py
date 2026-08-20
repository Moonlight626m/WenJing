"""Checkpoint 快照模型（design_04 §3.2）。

对应 `snapshots` 表：每 20 事件保存一次状态，加速回溯。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Snapshot(Base):
    """一次回溯可用的状态快照。"""

    __tablename__ = "snapshots"
    __table_args__ = (
        Index("idx_snapshots_session", "session_id", "event_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    event_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("events.id"), nullable=False
    )
    state_machine: Mapped[str] = mapped_column(Text)
    character_memories: Mapped[dict] = mapped_column(JSONB, default=dict)
    plot_context: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    event_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
