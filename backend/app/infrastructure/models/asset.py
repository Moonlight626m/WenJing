"""资产元数据模型（ADR-0005 §4/§6，issue #42）。

对应 `assets` 表：对象字节存对象存储，DB 只存元数据。契约层只暴露稳定
`AssetRef{asset_id,kind,status}`，`object_key` 仅存在于本表与 `ObjectStoragePort` 内部。
署名/许可字段（author/license/source_url/license_url）供详情页展示（#51/#54）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.session import Base
from app.infrastructure.models._time import utcnow


class Asset(Base):
    """一个多媒体资产（背景图/头像/立绘）的元数据。"""

    __tablename__ = "assets"
    __table_args__ = (
        Index("idx_assets_org_dedup", "org_id", "dedup_key"),
        Index("idx_assets_script", "script_id"),
        Index("idx_assets_session", "session_id"),
        {"extend_existing": True},
    )

    asset_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # 对象存储键；仅本表与 ObjectStoragePort 内部可见，不进契约
    object_key: Mapped[str] = mapped_column(String(512), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="generated")
    provider: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, index=True
    )
    script_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    # 去重键（org 作用域，ADR-0005 §6）；缓存命中即跳过付费调用
    dedup_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # 署名/许可（ADR-0005 §6）
    author: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    license: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    license_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
