"""Shared Contracts：核心 MVP 的唯一共享契约层。

版本化类型覆盖材料、证据、剧本、命令、领域事件、运行状态、快照、运行时更新、
对外错误与协议 DTO。契约是并行开发的边界：

- 领域模型与 REST/WS DTO 分离（见 `protocol.py`），转换只经 `mappers.py`。
- 变更流程见仓库根 `contracts/README.md`：breaking change 需至少两名模块 owner review。

契约命名 ↔ fixture ↔ 前后端类型的同步由后端测试
`backend/tests/test_contract_fixtures.py` 与前端 `tsc` 守卫。
"""

from __future__ import annotations

from app.contracts.commands import CommandStatus, CommandType, PlayerCommand
from app.contracts.errors import ErrorCode, ErrorDomains, ErrorEnvelope
from app.contracts.events import DomainEvent, EventType
from app.contracts.evidence import EvidenceRef, OriginalEvidenceRef, WebEvidenceRef
from app.contracts.material import GenreKind, Material, MaterialInput
from app.contracts.protocol import (
    GenerationCompleteMessage,
    GenerationFailedMessage,
    GenerationProgress,
    GenerationProgressMessage,
    GenerationView,
    MaterialReadyMessage,
    MaterialView,
    MessageType,
    OutboundMessage,
    RuntimeUpdateMessage,
    RuntimeView,
    ScriptView,
    SessionEndedMessage,
    SessionErrorMessage,
    SessionInitMessage,
    SessionInitPayload,
    SessionView,
)
from app.contracts.runtime import (
    ALLOWED_COMMANDS,
    CharacterState,
    GameSnapshot,
    GameStage,
    InteractionMode,
    InteractionPhase,
    InteractionPoint,
    RuntimeState,
    RuntimeStatus,
    RuntimeUpdate,
)
from app.contracts.script import Beat, CharacterSetting, Scene, ScriptPackage, Stage2Beat

__all__ = [
    "ALLOWED_COMMANDS",
    "Beat",
    "CharacterSetting",
    "CharacterState",
    "CommandStatus",
    "CommandType",
    "DomainEvent",
    "ErrorCode",
    "ErrorDomains",
    "ErrorEnvelope",
    "EventType",
    "EvidenceRef",
    "GameSnapshot",
    "GameStage",
    "GenerationCompleteMessage",
    "GenerationFailedMessage",
    "GenerationProgress",
    "GenerationProgressMessage",
    "GenerationView",
    "GenreKind",
    "InteractionMode",
    "InteractionPhase",
    "InteractionPoint",
    "Material",
    "MaterialInput",
    "MaterialReadyMessage",
    "MaterialView",
    "MessageType",
    "OriginalEvidenceRef",
    "OutboundMessage",
    "PlayerCommand",
    "RuntimeState",
    "RuntimeStatus",
    "RuntimeUpdate",
    "RuntimeUpdateMessage",
    "RuntimeView",
    "Scene",
    "ScriptPackage",
    "ScriptView",
    "SessionEndedMessage",
    "SessionErrorMessage",
    "SessionInitMessage",
    "SessionInitPayload",
    "SessionView",
    "Stage2Beat",
    "WebEvidenceRef",
]
