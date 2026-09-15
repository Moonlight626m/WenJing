"""运营后台契约（issue #22 / ADR-0002 §5）：只读剧本库 + token 用量聚合。

- 仅 `super_admin` 可访问；教师不可见学生游玩数据。
- token 聚合按 org / 时间 / 用途分组；剧本列表复用 `ScriptListResponse`。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.contracts.base import VersionedContract
from app.contracts.enums import UsagePurpose


class UsageAggregateRow(VersionedContract):
    """单个 (org, purpose) 分组的 token 聚合行。"""

    org_id: uuid.UUID
    purpose: UsagePurpose
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    call_count: int = Field(ge=0)


class UsageAggregateResponse(VersionedContract):
    """按 org/时间/用途过滤后的 token 聚合结果。"""

    items: list[UsageAggregateRow] = Field(default_factory=list)
    since: datetime | None = None
    until: datetime | None = None


__all__ = ["UsageAggregateRow", "UsageAggregateResponse"]
