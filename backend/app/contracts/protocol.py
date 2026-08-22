"""REST / WebSocket 协议 DTO 与消息。

领域模型与 DTO 分离：DTO 是设备边界，通过 `app.contracts.mappers` 显式转换，
禁止在路由/WS handler 中手工捏造 DTO。

- `OutboundMessage`：WebSocket 出站消息（按 type 判别的联合）；
  `sequence` 是 per-session 单调序号，是重连补发的依据。
- REST DTO：`SessionView` / `MaterialView` / `GenerationView` / `ScriptView` / `RuntimeView`。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.errors import ErrorEnvelope
from app.contracts.material import GenreKind
from app.contracts.runtime import (
    CommandType,
    GameStage,
    InteractionPhase,
    InteractionPoint,
    RuntimeStatus,
)
from app.contracts.script import ScriptPackage

PROTOCOL_SCHEMA_VERSION = 1


class MessageType(StrEnum):
    SESSION_INIT = "session_init"
    MATERIAL_READY = "material_ready"
    GENERATION_PROGRESS = "generation_progress"
    GENERATION_COMPLETE = "generation_complete"
    GENERATION_FAILED = "generation_failed"
    RUNTIME_UPDATE = "runtime_update"
    SESSION_ERROR = "session_error"
    SESSION_ENDED = "session_ended"


# ===== REST DTO =====


class SessionView(BaseModel):
    """会话概览（REST）。"""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    created_at: datetime
    status: Literal["created", "material_ready", "script_ready", "playing", "ended"]
    stage: GameStage = GameStage.INIT
    schema_version: int = PROTOCOL_SCHEMA_VERSION


class MaterialView(BaseModel):
    """材料视图（REST）。"""

    model_config = ConfigDict(extra="forbid")

    material_id: UUID
    session_id: UUID
    content_hash: str
    genre: GenreKind
    filename: str | None = None
    char_count: int = 0
    created_at: datetime
    schema_version: int = PROTOCOL_SCHEMA_VERSION


class GenerationProgress(BaseModel):
    """生成进度（classifying → researching → generating → validating）。"""

    model_config = ConfigDict(extra="forbid")

    step: Literal["classifying", "researching", "generating", "validating"]
    step_label: str
    progress: float = Field(ge=0.0, le=1.0)
    message: str = ""


class ScriptView(BaseModel):
    """剧本视图（REST / 生成完成消息）。"""

    model_config = ConfigDict(extra="forbid")

    script: ScriptPackage
    summary: str = ""
    schema_version: int = PROTOCOL_SCHEMA_VERSION


class GenerationView(BaseModel):
    """生成任务状态（REST 轮询）。"""

    model_config = ConfigDict(extra="forbid")

    status: Literal["running", "complete", "failed"]
    progress: GenerationProgress | None = None
    script: ScriptView | None = None
    error: ErrorEnvelope | None = None
    schema_version: int = PROTOCOL_SCHEMA_VERSION


class RuntimeView(BaseModel):
    """运行时视图（REST / WebSocket runtime_update 消息）。"""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    stage: GameStage
    phase: InteractionPhase | None = None
    interaction: InteractionPoint | None = None
    allowed_commands: list[CommandType] = Field(default_factory=list)
    status: RuntimeStatus = RuntimeStatus.RUNNING
    event_count: int = 0
    head_event_id: int = 0
    character_names: list[str] = Field(default_factory=list)
    player_role: str | None = None
    stage2_ending_confirmed: bool = False
    stage3_goal: str | None = None
    schema_version: int = PROTOCOL_SCHEMA_VERSION


# ===== WebSocket OutboundMessage =====


class _OutboundBase(BaseModel):
    """OutboundMessage 公共字段。"""

    model_config = ConfigDict(extra="forbid")

    message_id: UUID = Field(default_factory=uuid.uuid4)
    session_id: UUID
    correlation_id: UUID | None = None
    in_response_to_command_id: UUID | None = None
    sequence: int | None = None
    sent_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = PROTOCOL_SCHEMA_VERSION


class SessionInitPayload(BaseModel):
    """重连后一次性会话投影（阶段 + 已确认消息位置）。"""

    model_config = ConfigDict(extra="forbid")

    stage: GameStage
    phase: InteractionPhase | None = None
    last_acked_sequence: int | None = None
    runtime: RuntimeView | None = None


class SessionEndedPayload(BaseModel):
    """会话结束消息。"""

    model_config = ConfigDict(extra="forbid")

    reason: Literal["ended", "declined_stage3", "error"] = "ended"
    summary: str = ""


class SessionInitMessage(_OutboundBase):
    type: Literal["session_init"] = "session_init"
    payload: SessionInitPayload


class MaterialReadyMessage(_OutboundBase):
    type: Literal["material_ready"] = "material_ready"
    payload: MaterialView


class GenerationProgressMessage(_OutboundBase):
    type: Literal["generation_progress"] = "generation_progress"
    payload: GenerationProgress


class GenerationCompleteMessage(_OutboundBase):
    type: Literal["generation_complete"] = "generation_complete"
    payload: ScriptView


class GenerationFailedMessage(_OutboundBase):
    type: Literal["generation_failed"] = "generation_failed"
    payload: ErrorEnvelope


class RuntimeUpdateMessage(_OutboundBase):
    type: Literal["runtime_update"] = "runtime_update"
    payload: RuntimeView


class SessionErrorMessage(_OutboundBase):
    type: Literal["session_error"] = "session_error"
    payload: ErrorEnvelope


class SessionEndedMessage(_OutboundBase):
    type: Literal["session_ended"] = "session_ended"
    payload: SessionEndedPayload


OutboundMessage = Annotated[
    SessionInitMessage
    | MaterialReadyMessage
    | GenerationProgressMessage
    | GenerationCompleteMessage
    | GenerationFailedMessage
    | RuntimeUpdateMessage
    | SessionErrorMessage
    | SessionEndedMessage,
    Field(discriminator="type"),
]
