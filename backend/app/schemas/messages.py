from typing import Any

from pydantic import BaseModel

# ===== 后端 → 前端（design_02 消息协议骨架）=====
# 骨架阶段仅定义类型，不实现发送逻辑。


class NarrativeMessage(BaseModel):
    type: str = "narrative"
    id: int
    session_id: str
    content: dict[str, Any]
    timestamp: float


class CharacterSpeechMessage(BaseModel):
    type: str = "character_speech"
    id: int
    session_id: str
    content: dict[str, Any]
    timestamp: float


class InteractionMessage(BaseModel):
    type: str = "interaction"
    id: int
    session_id: str
    content: dict[str, Any]
    timestamp: float


class SystemMessage(BaseModel):
    type: str = "system"
    id: int
    session_id: str
    content: dict[str, Any]
    timestamp: float


class PhaseTransitionMessage(BaseModel):
    type: str = "phase_transition"
    id: int
    session_id: str
    content: dict[str, Any]
    timestamp: float


# ===== 前端 → 后端 =====


class PlayerActionMessage(BaseModel):
    type: str = "player_action"
    session_id: str
    content: dict[str, Any]
    timestamp: float


class RollbackRequestMessage(BaseModel):
    type: str = "rollback_request"
    session_id: str
    content: dict[str, Any]
    timestamp: float


class SystemCommandMessage(BaseModel):
    type: str = "system_command"
    session_id: str
    content: dict[str, Any]
    timestamp: float
