"""运行时契约：阶段、交互、显式运行状态、快照与运行时更新。

- `GameStage` / `InteractionPhase`：从 `app.core.state_machine` 提升到契约层的规范枚举
  （字符串值保持向后兼容；core 通过别名继续使用）。
- `RuntimeState`：显式、可序列化的游戏状态 —— 不含 WebSocket/FastAPI/SQLAlchemy/LLM client。
- `GameSnapshot`：恢复优化，不是事实来源。
- `RuntimeUpdate`：每次命令执行后的稳定输出，含新事件、当前交互与 allowed_commands。
- `ALLOWED_COMMANDS`：每阶段允许的命令表（RuntimeUpdate 消费）。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.commands import CommandType
from app.contracts.events import DomainEvent

RUNTIME_SCHEMA_VERSION = 1


class GameStage(StrEnum):
    """顶层游戏阶段（值向后兼容 core/state_machine 旧枚举）。"""

    INIT = "init"
    STAGE1_CREATING = "stage1_creating"
    STAGE1_COMPLETE = "stage1_complete"
    STAGE2_REENACTING = "stage2_reenacting"
    STAGE2_COMPLETE = "stage2_complete"
    STAGE3_EXTENDING = "stage3_extending"
    ENDED = "ended"


class InteractionPhase(StrEnum):
    """Stage2/3 内部的交互阶段（值向后兼容旧枚举）。"""

    NARRATIVE = "narrative"
    DIRECTION = "direction"
    AGENT_PROPOSAL = "agent_proposal"
    VERIFICATION = "verification"
    INTERACTION_DESIGN = "interaction_design"
    PLAYER_TURN = "player_turn"
    AGENT_REACTION = "agent_reaction"
    STAGE_CHECK = "stage_check"


class InteractionMode(StrEnum):
    """三种交互模式（与前端 InteractionMode 对齐）。"""

    OPTIONS = "options"
    FREE_INPUT = "free_input"
    OPTIONS_WITH_FALLBACK = "options_with_fallback"


class RuntimeStatus(StrEnum):
    RUNNING = "running"
    WAITING_PLAYER = "waiting_player"
    STAGE_COMPLETE = "stage_complete"
    ENDED = "ended"


class InteractionPoint(BaseModel):
    """当前交互点（玩家正在等什么）。"""

    model_config = ConfigDict(extra="forbid")

    mode: InteractionMode
    prompt: str
    options: list[str] = Field(default_factory=list)
    hint: str = ""
    character_name: str | None = None


class CharacterState(BaseModel):
    """角色运行时状态（身份 + 可序列化记忆）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    is_player: bool = False
    memory: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)


class RuntimeState(BaseModel):
    """显式游戏状态：progress 游标、Stage3 目标、角色记忆全部在此。"""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    stage: GameStage = GameStage.INIT
    phase: InteractionPhase | None = None
    active_branch_id: UUID
    head_event_id: int = 0
    event_count: int = 0
    beat_index: int = 0
    total_beats: int = 0
    stage2_ending_confirmed: bool = False
    stage3_goal: str | None = None
    stage3_round_taken: int = 0
    player_role: str | None = None
    characters: list[CharacterState] = Field(default_factory=list)
    plot_context: list[str] = Field(default_factory=list)
    schema_version: int = RUNTIME_SCHEMA_VERSION


class GameSnapshot(BaseModel):
    """运行时快照（性能优化；真相是事件流）。"""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: UUID
    session_id: UUID
    branch_id: UUID
    event_id: int = Field(ge=0)
    state: RuntimeState
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = RUNTIME_SCHEMA_VERSION


class RuntimeUpdate(BaseModel):
    """一次命令执行的稳定输出。"""

    model_config = ConfigDict(extra="forbid")

    state: RuntimeState
    events: list[DomainEvent] = Field(default_factory=list)
    interaction: InteractionPoint | None = None
    allowed_commands: frozenset[CommandType] = Field(default_factory=frozenset)
    status: RuntimeStatus = RuntimeStatus.RUNNING
    schema_version: int = RUNTIME_SCHEMA_VERSION


# 每阶段允许的命令表：RuntimeUpdate.allowed_commands 由此推导。
# 无游戏命令的阶段（创建/选角前）为空集；ENDED 后不可再提交。
ALLOWED_COMMANDS: dict[GameStage, frozenset[CommandType]] = {
    GameStage.INIT: frozenset(),
    GameStage.STAGE1_CREATING: frozenset(),
    GameStage.STAGE1_COMPLETE: frozenset(),
    GameStage.STAGE2_REENACTING: frozenset(
        {CommandType.CHOOSE_OPTION, CommandType.FREE_INPUT, CommandType.ROLLBACK}
    ),
    GameStage.STAGE2_COMPLETE: frozenset(
        {CommandType.CONFIRM_STAGE2_ENDING, CommandType.DECLINE_STAGE3, CommandType.ROLLBACK}
    ),
    GameStage.STAGE3_EXTENDING: frozenset(
        {
            CommandType.CHOOSE_OPTION,
            CommandType.FREE_INPUT,
            CommandType.ROLLBACK,
            CommandType.END_GAME,
        }
    ),
    GameStage.ENDED: frozenset(),
}
