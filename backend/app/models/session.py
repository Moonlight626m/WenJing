"""会话模型（issue #4 / design_04 §4.1）。

对应 PostgreSQL `sessions` 表：会话元数据 + 活动分支/head 指针 + 乐观锁版本号。
- `active_branch_id` 是对 event_branches 的逻辑引用（应用层保证存在性，
  不做库级外键以避免与 branches.session_id 形成循环依赖）。
- `version` 用于并发保护：一次命令处理 = 乐观锁下 version+1。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._time import utcnow


class Session(Base):
    """一场游戏会话的元数据、状态机当前状态与活动 head。"""

    __tablename__ = "sessions"
    __table_args__ = (
        Index("idx_sessions_active_branch", "active_branch_id"),
        {"extend_existing": True},
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 归属（ADR-0002）：隔离维度 + 拥有者（会话仅 owner 可见可玩）
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, index=True
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    current_stage: Mapped[str] = mapped_column(String(32), default="init")
    # 逻辑引用（无库级 FK，避免循环依赖）：指向 scripts.id 的「剧情世界」剧本
    script_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    player_role: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")

    # 活动 head 指针（回溯/恢复语义由 #8 落地）
    active_branch_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    head_event_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    # 乐观锁：UPDATE ... WHERE version = :expected 提供每会话单命令并发保护
    version: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
