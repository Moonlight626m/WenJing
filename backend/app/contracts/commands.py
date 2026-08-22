"""玩家命令契约：唯一游戏输入入口。

- `CommandType`：核心 MVP 的完整命令集合。
- `PlayerCommand`：携带唯一 command_id 与 session_id；payload 按命令类型严格校验，
  非法 payload 在契约层即被拒绝（不会进入领域状态）。
- `CommandStatus`：命令生命周期状态（持久化与幂等判定使用，ticket #4/#5 消费）。

每阶段 allowed_commands 表定义在 `app.contracts.runtime.ALLOWED_COMMANDS`
（由 RuntimeUpdate 消费，避免 contracts 内部循环依赖）。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

COMMANDS_SCHEMA_VERSION = 1


class CommandType(StrEnum):
    """玩家可提交的命令类型。"""

    CHOOSE_OPTION = "choose_option"
    FREE_INPUT = "free_input"
    ROLLBACK = "rollback"
    CONFIRM_STAGE2_ENDING = "confirm_stage2_ending"
    DECLINE_STAGE3 = "decline_stage3"
    END_GAME = "end_game"


class CommandStatus(StrEnum):
    """命令生命周期状态。"""

    PENDING = "pending"
    COMMITTED = "committed"
    REJECTED = "rejected"
    FAILED = "failed"


# 按命令类型校验 payload 的约定：
#   choose_option:   {"option_index": int >= 0}
#   free_input:      {"text": 非空 str}
#   rollback:        {"target_event_id": int} 或 {"steps": int >= 1}
#   其余命令:        payload 必须为空 {}
_PAYLOAD_RULES: dict[CommandType, str] = {
    CommandType.CHOOSE_OPTION: "option_index",
    CommandType.FREE_INPUT: "text",
    CommandType.ROLLBACK: "target_event_id|steps",
}


class PlayerCommand(BaseModel):
    """一条玩家命令。"""

    model_config = ConfigDict(extra="forbid")

    command_id: UUID = Field(default_factory=uuid.uuid4)
    session_id: UUID
    type: CommandType
    payload: dict[str, Any] = Field(default_factory=dict)
    issued_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = COMMANDS_SCHEMA_VERSION

    @model_validator(mode="after")
    def _payload_matches_type(self) -> PlayerCommand:
        if self.type is CommandType.CHOOSE_OPTION:
            idx = self.payload.get("option_index")
            if not isinstance(idx, int) or idx < 0:
                raise ValueError("choose_option 需要 payload.option_index (int >= 0)")
        elif self.type is CommandType.FREE_INPUT:
            text = self.payload.get("text")
            if not isinstance(text, str) or not text.strip():
                raise ValueError("free_input 需要 payload.text (非空 str)")
        elif self.type is CommandType.ROLLBACK:
            has_target = isinstance(self.payload.get("target_event_id"), int)
            has_steps = isinstance(self.payload.get("steps"), int) and self.payload["steps"] >= 1
            if not (has_target or has_steps):
                raise ValueError("rollback 需要 payload.target_event_id 或 payload.steps (>=1)")
        elif self.payload:
            raise ValueError(f"{self.type.value} 不允许携带 payload")
        return self
