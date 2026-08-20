"""会话模型（design_04 §4.1）。

对应 PostgreSQL `sessions` 表：游戏会话元数据与状态机当前状态。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Session(Base):
    """一场游戏会话的元数据与当前状态。"""

    __tablename__ = "sessions"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    current_stage: Mapped[str] = mapped_column(String(32), default="init")
    script_id: Mapped[int | None] = mapped_column(
        ForeignKey("scripts.id"), nullable=True
    )
    material_id: Mapped[int | None] = mapped_column(
        ForeignKey("materials.id"), nullable=True
    )
    player_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
