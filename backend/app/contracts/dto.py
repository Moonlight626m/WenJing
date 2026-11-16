"""REST/WebSocket 协议 DTO 与显式 mapper。

- 领域契约（material/script/runtime/…）与对外协议 DTO 在此分离。
- 所有转换经本模块的显式函数完成，禁止消费者直接把领域模型当 DTO 发送。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import Field, TypeAdapter

from app.contracts.base import ContractModel, VersionedContract
from app.contracts.commands import PlayerCommand
from app.contracts.enums import MessageCategory
from app.contracts.errors import ErrorEnvelope
from app.contracts.runtime import ActiveInteraction
from app.contracts.script import AssetRef

# ===== REST DTO =====


class CreateSessionRequest(VersionedContract):
    """POST /api/sessions：从可见剧本开一局「剧情世界」。"""

    script_id: int = Field(ge=1)


class CreateSessionResponse(ContractModel):
    """内部：新建会话行后的响应（对外开局端点返回 SessionStatusResponse）。"""

    session_id: uuid.UUID
    created_at: datetime | None = None


class SessionSummary(VersionedContract):
    """「我的游戏」列表项：会话元数据 + 引用剧本名。"""

    session_id: uuid.UUID
    script_id: int | None = None
    script_name: str | None = None
    stage: str
    status: str
    player_role: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class SessionListResponse(VersionedContract):
    """「我的游戏」列表（当前用户自己的剧情世界）。"""

    items: list[SessionSummary] = Field(default_factory=list)


class SessionStatusResponse(ContractModel):
    """GET /api/sessions/{id} 状态查询。"""

    session_id: uuid.UUID
    stage: str
    active_branch_id: uuid.UUID
    head_sequence: int = Field(ge=0)
    playable_roles: list[str] = Field(default_factory=list)
    selected_role: str | None = None


class CommandStatusResponse(ContractModel):
    """GET /api/sessions/{id}/commands/{command_id}：异步命令落地状态。

    roles 页轮询它来区分「还在跑」与「已经失败」——会话状态本身不暴露命令
    台账，只轮询 stage/selected_role 会让失败一直等到前端超时。
    `status` 为 None 表示命令未受理（command_id 不属于该会话或从未提交）。
    `inflight` 表示本进程仍有该命令的后台 task：`received` 且非在途 =
    上个进程留下的孤儿受理，调用方应换新 command_id 重试。
    """

    command_id: uuid.UUID
    status: Literal["received", "succeeded", "failed"] | None = None
    inflight: bool = False


class TimelineEntry(ContractModel):
    """回溯页的一条进度：活动分支上**已发生**的事件投影。

    与 WS 消息同一套投影（seq = 分支路径序号，回溯命令按它定位目标），额外带上
    累计的场景上下文（图/标题）——回溯页据此给每幕配图并写描述。未来场景从不
    出现在这里：它只遍历 `active_events()`，而不是剧本包的 `scenes`。
    """

    sequence: int = Field(ge=0)
    #: 对外坐标的另一半：事件 UUID 与所属分支（跨端稳定，回溯首选坐标）
    event_id: uuid.UUID
    branch_id: uuid.UUID
    kind: MessageCategory
    text: str
    speaker: str | None = None
    scene_key: str | None = None
    scene_title: str | None = None
    current_asset: AssetRef | None = None
    #: 只有叙事节拍是回溯目标：回溯按 beat 游标恢复，落在台词/系统提示上会让
    #: 「回到哪一幕」变得不可预期。
    rollbackable: bool = False


class SavePoint(ContractModel):
    """回溯页的存档点卡片：快照坐标 + 人读标记（场景/命令/回溯）。"""

    branch_id: uuid.UUID
    sequence: int = Field(ge=0)
    event_id: uuid.UUID
    label: str
    kind: str = "command"
    created_at: datetime | None = None


class BranchSummary(ContractModel):
    """回溯页的分支切换项：活动分支可继续玩，其余分支只读。"""

    branch_id: uuid.UUID
    is_active: bool
    event_count: int = Field(ge=0)


class SessionTimelineResponse(ContractModel):
    """GET /api/sessions/{id}/timeline：独立回溯页的数据源。

    与 `SessionStatusResponse` 同属**未导出的 REST DTO**（`ContractModel`，不带
    `schema_version`）——因此不进 fixtures/jsonschema；前端镜像与状态响应一样
    手写在 `frontend/src/lib/api.ts`。
    """

    session_id: uuid.UUID
    stage: str
    head_sequence: int = Field(ge=0)
    can_rollback: bool = False
    #: 本次返回的是哪条分支：默认活动分支；`?branch_id=` 可查看旧分支（只读）
    branch_id: uuid.UUID | None = None
    read_only: bool = False
    save_points: list[SavePoint] = Field(default_factory=list)
    branches: list[BranchSummary] = Field(default_factory=list)
    entries: list[TimelineEntry] = Field(default_factory=list)


# ===== WebSocket 协议 =====


class InteractionPayload(ContractModel):
    """当前交互点投影：前端据此渲染三输入模式。"""

    interaction_id: str
    mode: str
    prompt: str
    options: list[dict] = Field(default_factory=list)
    hint: str = ""


def interaction_to_payload(interaction: ActiveInteraction) -> InteractionPayload:
    """领域交互点 → WS 投影（显式 mapper）。"""
    return InteractionPayload(
        interaction_id=interaction.interaction_id,
        mode=interaction.mode.value,
        prompt=interaction.prompt,
        options=[opt.model_dump() for opt in interaction.options],
        hint=interaction.hint,
    )


def error_to_payload(error: ErrorEnvelope) -> dict[str, Any]:
    """错误 envelope → 安全对外 dict（不含 cause/stack）。"""
    return {
        "error_id": str(error.error_id),
        "code": error.code,
        "domain": error.domain.value,
        "message": error.message,
        "retryable": error.retryable,
        "details": error.details,
    }


class ContentBlock(ContractModel):
    """叙事内容块：category 决定前端渲染方式。"""

    category: MessageCategory
    speaker: str | None = None
    text: str


class ServerMessage(VersionedContract):
    """服务端 WS 消息封套；seq 用于确认与重连补发。

    - `seq` 在会话内单调递增，客户端以 last_confirmed_seq 恢复。
    - `payload` 按 type 判别（见 ClientMessage 侧注释）。
    - 瞬态流式消息**不在本模型**：它们没有 seq、不进 outbox，见 `StreamMessage`。
    """

    type: str = Field(
        description=(
            "session_init|narrative|character_speech|system|interaction"
            "|asset_ready|error"
        )
    )
    session_id: uuid.UUID
    seq: int = Field(ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)


class StreamMessage(ContractModel):
    """瞬态流式消息（ADR-0005 §10 / #60）：**有 type 无 seq**。

    `stream_start{stream_id, speaker}` → `stream_delta{stream_id, text}` × N →
    `stream_end{stream_id}`。它描述的是"此刻屏幕上滚动的字幕"，不参与
    `seq`/`confirm`/`resync` 补发；权威文本永远是随后那条带 seq 的
    `character_speech`——前端收到它即丢弃对应 `stream_id` 的流缓冲。
    """

    type: Literal["stream_start", "stream_delta", "stream_end"]
    session_id: uuid.UUID
    payload: dict[str, Any] = Field(default_factory=dict)


class AudioStartMessage(ContractModel):
    """音轨开始（ADR-0005 §11 / #63）：**有 type 无 seq**，与 `StreamMessage` 同类。

    紧随其后的是**裸二进制帧**（音频字节），由 `AudioEndMessage` 收尾。一条发言
    一条音轨，多角色并发时前端挂多个 `<audio>`；后端不混音。

    `codec` 是 MIME（`audio/mpeg` 等），不是裸格式名——前端直接喂
    `Blob([bytes], {type: codec})` 造 `objectURL`，不必再维护一张格式映射表。
    """

    type: Literal["audio_start"] = "audio_start"
    session_id: uuid.UUID
    payload: dict[str, Any] = Field(default_factory=dict)


class AudioEndMessage(ContractModel):
    """音轨结束：该 `track_id` 的二进制帧到此为止。"""

    type: Literal["audio_end"] = "audio_end"
    session_id: uuid.UUID
    payload: dict[str, Any] = Field(default_factory=dict)


class SubmitCommandMessage(ContractModel):
    """客户端提交命令（PlayerCommand 直接作为 payload 强校验）。"""

    type: Literal["submit_command"] = "submit_command"
    command: PlayerCommand


class ConfirmMessagesMessage(ContractModel):
    """客户端确认已收到 seq（幂等对账与补发锚点）。"""

    type: Literal["confirm_messages"] = "confirm_messages"
    last_confirmed_seq: int = Field(ge=0)


class ResyncRequestMessage(ContractModel):
    """客户端请求从指定位置重建投影（重连恢复）。"""

    type: Literal["resync_request"] = "resync_request"
    last_confirmed_seq: int = Field(ge=0)


class CancelAudioMessage(ContractModel):
    """客户端打断（barge-in，ADR-0005 §11）：停播并放掉这条音轨。

    **不抢占 LLM**：命令仍串行、事件同事务持久化，服务端在生成中根本收不到新命令，
    所以打断只可能作用于已经流到客户端的那条音轨。音频出口是 M6（#63）：今天没有
    音轨可取消，服务端只需接受这条消息而不是把它当畸形帧。
    """

    type: Literal["cancel_audio"] = "cancel_audio"
    track_id: str = Field(min_length=1)


ClientMessage = Annotated[
    SubmitCommandMessage
    | ConfirmMessagesMessage
    | ResyncRequestMessage
    | CancelAudioMessage,
    Field(discriminator="type"),
]

client_message_adapter: TypeAdapter[SubmitCommandMessage
                                   | ConfirmMessagesMessage
                                   | ResyncRequestMessage
                                   | CancelAudioMessage] = TypeAdapter(ClientMessage)
