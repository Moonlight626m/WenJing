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


class PromptEntry(VersionedContract):
    """单条 prompt 覆盖行（PromptMgr 组件；管理界面按 stage 分组）。"""

    stage: str
    node: str
    version: str
    section: str
    body: str
    description: str | None = None
    enabled: bool = True
    updated_at: datetime | None = None


class PromptListResponse(VersionedContract):
    """prompt 覆盖层列表（可按 stage 过滤）。"""

    items: list[PromptEntry] = Field(default_factory=list)


class PromptUpdateRequest(VersionedContract):
    """prompt 更新载荷：提供 body 即更新文案；enabled=false 关闭该段覆盖。"""

    body: str | None = Field(default=None, min_length=1)
    description: str | None = None
    enabled: bool | None = None


__all__ = [
    "UsageAggregateRow",
    "UsageAggregateResponse",
    "PromptEntry",
    "PromptListResponse",
    "PromptUpdateRequest",
]
