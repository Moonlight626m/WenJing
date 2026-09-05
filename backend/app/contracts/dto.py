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

# ===== REST DTO =====


class CreateSessionResponse(ContractModel):
    """POST /api/sessions 响应。"""

    session_id: uuid.UUID
    created_at: datetime | None = None


class SessionStatusResponse(ContractModel):
    """GET /api/sessions/{id} 状态查询。"""

    session_id: uuid.UUID
    stage: str
    active_branch_id: uuid.UUID
    head_sequence: int = Field(ge=0)
    playable_roles: list[str] = Field(default_factory=list)
    selected_role: str | None = None
    generation: GenerationProgress | None = None


class GenerationPhaseState(ContractModel):
    """单个生成阶段（体裁判断/网络研究/生成/验证）的状态。"""

    name: str
    state: Literal["pending", "running", "succeeded", "failed", "degraded"]
    detail: str | None = None


class GenerationProgress(ContractModel):
    """生成进度：长时间生成过程不是黑盒。"""

    status: Literal["idle", "running", "succeeded", "failed"]
    phases: list[GenerationPhaseState] = Field(default_factory=list)


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
    """

    type: str = Field(
        description="session_init|narrative|character_speech|system|interaction|error"
    )
    session_id: uuid.UUID
    seq: int = Field(ge=0)
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


ClientMessage = Annotated[
    SubmitCommandMessage | ConfirmMessagesMessage | ResyncRequestMessage,
    Field(discriminator="type"),
]

client_message_adapter: TypeAdapter[SubmitCommandMessage
                                   | ConfirmMessagesMessage
                                   | ResyncRequestMessage] = TypeAdapter(ClientMessage)
