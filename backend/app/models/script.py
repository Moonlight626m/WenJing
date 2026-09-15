"""剧本模型（design_04 §4.2）。

对应 `scripts` 表：Stage1 生成的剧本（场景序列/角色设定表）+ 验证结果（JSONB）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._time import utcnow


class Script(Base):
    """一份 Stage1 生成的剧本。"""

    __tablename__ = "scripts"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[str] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sessions.id"), nullable=False
    )
    # 归属（ADR-0002）：剧本可复用实体，独立归属 owner/org（#19 起与 session 解绑）
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text)
    script_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
