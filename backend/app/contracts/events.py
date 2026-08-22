"""领域事件契约：游戏事实的唯一来源（append-only）。

每个事件标识 session、branch、sequence、causation（哪个命令触发）、correlation（关联链）
与 schema_version。WebSocket 消息只是这些事件的展示投影，重连时可重建。

payload 保持 `dict[str, Any]`：具体事件类型的 payload 键约定见本模块文档字符串，
ticket #7（GameRuntime 重构）落地时若需更严格的判别式 payload，走版本化扩展。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

EVENTS_SCHEMA_VERSION = 1


class EventType(StrEnum):
    STAGE_TRANSITIONED = "stage_transitioned"
    SCRIPT_LOADED = "script_loaded"
    INTERACTION_PRESENTED = "interaction_presented"
    PLAYER_ACTED = "player_acted"
    NARRATIVE_ADVANCED = "narrative_advanced"
    CHARACTER_SPOKE = "character_spoke"
    ROLLBACK_EXECUTED = "rollback_executed"
    BRANCH_CREATED = "branch_created"
    STAGE3_GOAL_UPDATED = "stage3_goal_updated"
    GAME_ENDED = "game_ended"


class DomainEvent(BaseModel):
    """单条领域事件。"""

    model_config = ConfigDict(extra="forbid")

    event_id: int = Field(ge=0)
    session_id: UUID
    branch_id: UUID
    sequence: int = Field(ge=0)
    type: EventType
    causation_id: UUID | None = None
    correlation_id: UUID = Field(default_factory=uuid.uuid4)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    payload: dict[str, Any] = Field(default_factory=dict)
    schema_version: int = EVENTS_SCHEMA_VERSION
