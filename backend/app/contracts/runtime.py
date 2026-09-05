"""运行时状态契约：RuntimeState / GameSnapshot / RuntimeUpdate。

- 全部进度游标、Stage3 目标、角色记忆、剧情上下文都是显式版本化运行时状态
  （spec 决策），快照 + 事件重放可重建相同状态。
- RuntimeState 不含 WebSocket / SQLAlchemy / LLM client 等基础设施对象。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field

from app.contracts.base import VersionedContract
from app.contracts.enums import CommandKind, EventType, InteractionMode, StageValue


class OptionItem(VersionedContract):
    """交互点的单个选项。"""

    option_id: str
    label: str


class ActiveInteraction(VersionedContract):
    """当前等待玩家响应的交互点（稳定交互点语义）。"""

    interaction_id: str = Field(min_length=1)
    mode: InteractionMode
    prompt: str
    options: list[OptionItem] = Field(default_factory=list)
    hint: str = ""

    def allowed_command_kinds(self) -> list[CommandKind]:
        """按模式推导当前允许的输入命令。"""
        base: set[CommandKind]
        if self.mode == InteractionMode.OPTIONS:
            base = {CommandKind.CHOOSE_OPTION}
        elif self.mode == InteractionMode.FREE_INPUT:
            base = {CommandKind.FREE_INPUT}
        else:  # OPTIONS_WITH_FALLBACK
            base = {CommandKind.CHOOSE_OPTION, CommandKind.FREE_INPUT}
        return sorted(base, key=lambda k: k.value)


class Stage3Goal(VersionedContract):
    """Stage 3 续写的小目标：目标导向自然收敛（spec 决策）。"""

    goal_id: int
    description: str
    achieved: bool = False


class RuntimeState(VersionedContract):
    """显式、可序列化的运行时状态；恢复/回放的重建目标。"""

    session_id: uuid.UUID
    branch_id: uuid.UUID
    last_sequence: int = Field(ge=0)

    stage: StageValue
    phase: str | None = None

    # 进度游标与剧情上下文
    scene_id: int | None = None
    beat_cursor: int | None = None
    plot_context: dict = Field(default_factory=dict)

    # 角色记忆：role_name -> memory entries（显式，不藏在对象字段里）
    character_memories: dict[str, list[str]] = Field(default_factory=dict)

    # 当前活动交互点（无则引擎处于推进态）
    active_interaction: ActiveInteraction | None = None

    # Stage3 目标状态
    stage3_goals: list[Stage3Goal] = Field(default_factory=list)

    def allowed_commands(self) -> list[CommandKind]:
        """当前阶段允许的命令集合（from enums.ALLOWED_COMMANDS）。"""
        from app.contracts.enums import ALLOWED_COMMANDS

        return sorted(
            ALLOWED_COMMANDS[self.stage], key=lambda k: k.value
        )


class GameSnapshot(VersionedContract):
    """运行时快照：性能优化而非真相；从兼容快照 + 后续事件恢复（spec 决策）。"""

    snapshot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    branch_id: uuid.UUID
    last_sequence: int = Field(ge=0)
    state: RuntimeState
    created_at: datetime | None = None


class RuntimeUpdate(VersionedContract):
    """一次命令推进的结果：提交后到下一个稳定交互点或终态返回。

    含状态、新事件、活动交互与允许命令——session 层据此投影对外消息。
    """

    session_id: uuid.UUID
    branch_id: uuid.UUID
    state: RuntimeState
    new_events: list[DomainEventRef] = Field(default_factory=list)
    terminal: bool = False
    emitted_event_types: list[EventType] = Field(default_factory=list)


class DomainEventRef(VersionedContract):
    """RuntimeUpdate 内的事件引用（完整 DomainEvent 由 event store 持久化）。"""

    event_id: uuid.UUID
    sequence: int
    event_type: EventType
