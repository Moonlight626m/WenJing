"""prompt 模板模型（PromptMgr 组件）：对应 `prompts` 表。

- prompt 文案的 DB 覆盖层：键为「阶段 × 节点 × 版本 × 段落」四维唯一；
- 代码内 defaults（domain/prompts/defaults.py）是单源，本表只存覆盖行；
- 版本升级 = 写入新 version 行 + 旧行 enabled=false，历史自然留痕；
- 输出契约文本（字段类型说明）不落库，留在代码与 Pydantic 契约同步。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.session import Base
from app.infrastructure.models._time import utcnow


class PromptTemplate(Base):
    """一段可覆盖的 prompt 文案（如 script_gen / divide_events / v2 / system）。"""

    __tablename__ = "prompts"
    __table_args__ = (
        UniqueConstraint(
            "stage", "node", "version", "section", name="uq_prompts_key"
        ),
        {"extend_existing": True},
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    stage: Mapped[str] = mapped_column(String(40), nullable=False)
    node: Mapped[str] = mapped_column(String(60), nullable=False)
    version: Mapped[str] = mapped_column(String(20), nullable=False)
    section: Mapped[str] = mapped_column(String(60), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
