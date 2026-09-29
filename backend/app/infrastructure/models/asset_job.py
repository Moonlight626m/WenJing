"""运行期配图任务模型（ADR-0005 §5，issue #57）。

对应 `asset_jobs` 表：**运行期**（Stage3）每一次配图尝试一行，`pending` 表示
「已发起、未收口」。它存在的两个理由（详见 `domain/game/media.py::AssetJobPort`）：

- `assets` 行必须记在**剧本**名下（否则跨会话缓存复用会因会话 owner 鉴权变 403），
  于是「按会话」的账——每会话生图上限、崩溃后重排——只能记在这张表上；
- 这张账必须跨进程存活：进程内计数器一重启就归零，崩溃循环里的会话能绕开上限。

`session_id`/`script_id`/`user_id` 是逻辑引用（无库级 FK，与 `assets` 一致），
`org_id` 带 FK。生成期的批量配图（#48）不走这张表——它的幂等由去重键承担。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.session import Base
from app.infrastructure.models._time import utcnow


class AssetJob(Base):
    """一次运行期配图尝试。"""

    __tablename__ = "asset_jobs"
    __table_args__ = (
        # 去重键的持久形态：同一会话的同一场景只有一条尝试记录。
        # 进程内去重集合（`SceneAssetScheduler._attempted`）一重启就没了，
        # 这条唯一约束才是「不重复付费」跨进程的那一半。
        UniqueConstraint("session_id", "scene_key", name="uq_asset_jobs_session_scene"),
        Index("idx_asset_jobs_status_created", "status", "created_at"),
        Index("idx_asset_jobs_session", "session_id"),
        {"extend_existing": True},
    )

    job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    branch_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    scene_key: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, index=True
    )
    script_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    asset_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    #: 失败原因摘要（诊断/失败率归因）；成功时为空
    reason: Mapped[str] = mapped_column(String(200), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
