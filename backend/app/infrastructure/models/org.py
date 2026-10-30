"""组织模型（issue #17 / ADR-0002 §1）。

对应 `orgs` 表：MVP 所有账号归属一个默认组织「文境演示学校」；多组织为后续需求，
此处预留 `org_id` 隔离维度，避免以后全表迁移。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.infrastructure.db.session import Base
from app.infrastructure.models._time import utcnow


class Org(Base):
    """租户组织。"""

    __tablename__ = "orgs"
    __table_args__ = {"extend_existing": True}

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow
    )
