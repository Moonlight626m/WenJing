"""LLM 用量模型（issue #22 / ADR-0002 §5）。

对应 `llm_usage` 表：**逐次 LLM 调用**一条记录，append-only 计量事实。
- provider/model/purpose 标识调用来源；prompt/completion/total 为 token 数；
- org_id/user_id 为强归属（带 FK）；script_id/session_id 为逻辑引用（无 FK），
  避免删除草稿剧本或回收空壳会话时被计量历史的外键阻塞。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._time import utcnow


class LlmUsage(Base):
    """一次 LLM 调用的 token 计量记录。"""

    __tablename__ = "llm_usage"
    __table_args__ = (
        Index("idx_llm_usage_org_created", "org_id", "created_at"),
        Index("idx_llm_usage_purpose_created", "purpose", "created_at"),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)

    prompt_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False)

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

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )
