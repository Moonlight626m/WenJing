"""剧本生成尝试记录（issue #28）。

对应 `script_generations` 表：一次 workflow 生成尝试的观测面。
- LangGraph checkpointer（AsyncPostgresSaver，自建 4 张表）负责可恢复性；
- 本表负责业务观测：每节点状态 / doubter 事件 / 错误，教师端经
  `GenerationProgress` 契约读取。同一剧本可有多次尝试（重新生成 = 新行）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.models._time import utcnow


class ScriptGeneration(Base):
    """一次剧本生成尝试（workflow 运行的观测与断点记录）。"""

    __tablename__ = "script_generations"
    __table_args__ = {"extend_existing": True}

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # 剧本删除时连同其生成记录一并删除（进度属剧本的从属数据）
    script_id: Mapped[int] = mapped_column(
        ForeignKey("scripts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # 归属镜像（剧本所属 org/owner，避免每次 join）
    org_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orgs.id"), nullable=False
    )
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    # LangGraph checkpointer thread id（新尝试 = 新 thread；闸门恢复用）
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # running | awaiting_review | succeeded | failed（contracts.generation.GenerationStatus）
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    # NodeProgress/DoubterEvent 快照（GenerationProgress.nodes + doubter_events 的落库形态）
    progress: Mapped[dict] = mapped_column(JSONB, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
