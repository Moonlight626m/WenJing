"""领域事件契约：DomainEvent —— 游戏事实来源。

每个事件标识 session、branch、sequence、causation、correlation 与 schema 版本（spec 决策）。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from app.contracts.base import VersionedContract
from app.contracts.enums import EventType


class DomainEvent(VersionedContract):
    """已发生的游戏事实；只追加，不可变。

    sequence 在 (session_id, branch_id) 内单调递增；
    causation_id 指向引发本事件的命令/事件 ID，correlation_id 串联同一命令的因果链。
    """

    event_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    branch_id: uuid.UUID
    sequence: int = Field(ge=0)
    event_type: EventType
    causation_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    occurred_at: datetime | None = None


class BranchInfo(VersionedContract):
    """事件分支元数据：回溯创建新分支时登记。"""

    branch_id: uuid.UUID
    session_id: uuid.UUID
    root_sequence: int = Field(ge=0, description="新分支从此继承序列之后开始")
    parent_branch_id: uuid.UUID | None = None
    created_by_command_id: uuid.UUID | None = None
