"""媒体用量模型（issue #41 / ADR-0005 §12）。

对应 `media_usage` 表：**逐次媒体调用**一条记录，append-only 计量事实，best-effort。
与 token 语义的 `llm_usage` 分离：
- `kind`=image|tts|asr；`provider`/`model` 标识来源；`units` 为张/字符/秒，`size` 为字节；
- `org_id`/`user_id` 为强归属（带 FK）；`script_id`/`session_id` 为逻辑引用（无 FK）；
- `meta` JSONB 存 provider 附加信息（尺寸、时长、缓存命中等）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.session import Base
from app.infrastructure.models._time import utcnow


class MediaUsage(Base):
    """一次媒体调用（图片/TTS/ASR）的计量记录。"""

    __tablename__ = "media_usage"
    __table_args__ = (
        Index("idx_media_usage_org_created", "org_id", "created_at"),
        Index("idx_media_usage_kind_created", "kind", "created_at"),
        Index("idx_media_usage_session", "session_id"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # units：图片=张、TTS=字符、ASR=秒；size：产出字节数
    units: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    # 逻辑引用（无 FK）：剧本可删除、空壳会话可回收，计量历史独立留存
    script_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
