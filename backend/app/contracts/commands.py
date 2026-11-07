"""玩家命令契约：PlayerCommand 及按 kind 判别的 payload。

- PlayerCommand 是唯一游戏输入入口，携带唯一 command ID 与 session ID（spec 决策）。
- 重复 command ID 必须幂等：runtime 与 session 层据此去重。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, model_validator

from app.contracts.base import VersionedContract
from app.contracts.enums import CommandKind


class CommandPayload(VersionedContract):
    """命令 payload 基类：kind 由外层 PlayerCommand 携带。"""


class SelectRolePayload(CommandPayload):
    role_name: str = Field(min_length=1)


class ChooseOptionPayload(CommandPayload):
    option_id: str = Field(min_length=1)


class TextPayload(CommandPayload):
    """自然语言 payload：自由发言与玩家干涉共用同一条长度约束。"""

    text: str = Field(min_length=1, max_length=2000)


class FreeInputPayload(TextPayload):
    """玩家自由发言（Stage3）。"""


class IntervenePayload(TextPayload):
    """玩家干涉世界：建场景 / 拉入或新增角色，由 ProducerAgent 解析。"""


class RollbackToEventPayload(CommandPayload):
    """回溯目标：活动分支上的事件坐标（回溯不物理删除历史）。

    两种坐标二选一（都有效时 `target_event_id` 优先）：
    - `target_event_id`：契约事件 UUID（`TimelineEntry.event_id`），跨端稳定；
    - `target_sequence`：活动分支路径下标（旧坐标，与 WS 消息 `seq` 同口径）。
    """

    target_event_id: uuid.UUID | None = None
    target_sequence: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _require_target(self) -> RollbackToEventPayload:
        if self.target_event_id is None and self.target_sequence is None:
            raise ValueError("target_event_id 与 target_sequence 至少提供一个")
        return self


class SwitchScenePayload(CommandPayload):
    """换景目标：交互点 `scene_options` 里的 `scene_key`（如 `loc:harbor`）。"""

    scene_key: str = Field(min_length=1)


class EmptyPayload(CommandPayload):
    """无参命令（enter_stage3 / confirm_ending / exit_game）。"""


_PAYLOAD_BY_KIND: dict[CommandKind, type[CommandPayload]] = {
    CommandKind.SELECT_ROLE: SelectRolePayload,
    CommandKind.CHOOSE_OPTION: ChooseOptionPayload,
    CommandKind.FREE_INPUT: FreeInputPayload,
    CommandKind.INTERVENE: IntervenePayload,
    CommandKind.SWITCH_SCENE: SwitchScenePayload,
    CommandKind.ROLLBACK_TO_EVENT: RollbackToEventPayload,
    CommandKind.ENTER_STAGE3: EmptyPayload,
    CommandKind.CONFIRM_ENDING: EmptyPayload,
    CommandKind.EXIT_GAME: EmptyPayload,
}


class PlayerCommand(VersionedContract):
    """玩家命令：唯一游戏输入入口；command_id 幂等键。"""

    command_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    session_id: uuid.UUID
    kind: CommandKind
    payload: dict = Field(default_factory=dict)
    issued_at: datetime | None = None

    @property
    def payload_model(self) -> CommandPayload:
        """把 dict payload 解析为对应类型的强校验模型。"""
        return _PAYLOAD_BY_KIND[self.kind].model_validate(self.payload)

    @model_validator(mode="after")
    def _validate_payload(self) -> PlayerCommand:
        # 提前校验 payload 匹配 kind，畸形命令在入口即被拒绝
        self.payload_model
        return self
