"""ORM 模型统一入口。

导入本包即把全部模型注册到 `app.db.session.Base.metadata`
（供 Alembic autogenerate 与建表使用）。
"""

from __future__ import annotations

from app.models.auth_session import AuthSession
from app.models.command import CommandRecord, CommandStatus
from app.models.event import EVENTS_SCHEMA_VERSION, GameEventRecord
from app.models.event_branch import EventBranchRecord
from app.models.llm_usage import LlmUsage
from app.models.material import Material
from app.models.org import Org
from app.models.script import Script
from app.models.script_generation import ScriptGeneration
from app.models.session import Session
from app.models.snapshot import Snapshot
from app.models.user import User

__all__ = [
    "Session",
    "Material",
    "Script",
    "ScriptGeneration",
    "EventBranchRecord",
    "GameEventRecord",
    "EVENTS_SCHEMA_VERSION",
    "CommandRecord",
    "CommandStatus",
    "Snapshot",
    "Org",
    "User",
    "AuthSession",
    "LlmUsage",
]

# 确保做元数据收集时模型已全部导入（Base.metadata 上注册）
_ = (
    Session,
    Material,
    Script,
    ScriptGeneration,
    EventBranchRecord,
    GameEventRecord,
    CommandRecord,
    Snapshot,
    Org,
    User,
    AuthSession,
    LlmUsage,
)
