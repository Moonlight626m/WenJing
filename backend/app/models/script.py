"""剧本模型（design_04 §4.2 / ADR-0002 §3）。

对应 `scripts` 表：可复用剧本实体（名称/描述/场景序列/角色设定表）。
不再绑定 session：一局「剧情世界」经 `sessions.script_id` 引用；同一素材可生成
多个独立剧本。`status` 为 draft|published|unpublished，`visibility` 为 org|public。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._time import utcnow


class Script(Base):
    """一份可复用剧本（Stage1 生成的场景序列/角色设定表 + 生命周期）。"""

    __tablename__ = "scripts"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 归属（ADR-0002）：独立归属 owner/org，作为隔离与可见性判定依据
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 来源素材（同一素材可生成多个剧本）
    material_id: Mapped[int | None] = mapped_column(
        ForeignKey("materials.id"), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    visibility: Mapped[str] = mapped_column(String(16), nullable=False, default="org")
    # 生成成功后写入 ScriptPackage；草稿/生成失败时为 NULL
    script_data: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    verification: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
