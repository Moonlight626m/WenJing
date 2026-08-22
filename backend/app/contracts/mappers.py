"""显式 mapper 契约：领域模型 → REST/WS DTO 的唯一转换路径。

规则：
- 每个 mapper 是纯函数，输入契约模型、输出 DTO；不得持有状态。
- 禁止在路由 / WS handler 中手工构造 DTO；一律经本模块转换。
- 新 DTO 出现时，先在这里补 mapper + 测试，再被协议层使用。
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

from app.contracts.errors import ErrorCode, ErrorEnvelope
from app.contracts.material import Material
from app.contracts.protocol import MaterialView, RuntimeView, ScriptView
from app.contracts.runtime import RuntimeUpdate
from app.contracts.script import ScriptPackage


def material_to_view(material: Material, *, char_count: int | None = None) -> MaterialView:
    """Material → MaterialView（char_count 默认取规范化文本长度）。"""
    return MaterialView(
        material_id=material.material_id,
        session_id=material.session_id,
        content_hash=material.content_hash,
        genre=material.genre,
        filename=material.filename,
        char_count=len(material.raw_text) if char_count is None else char_count,
        created_at=material.created_at,
    )


def script_to_view(script: ScriptPackage, *, summary: str = "") -> ScriptView:
    """ScriptPackage → ScriptView。"""
    return ScriptView(script=script, summary=summary)


def update_to_runtime_view(session_id: UUID, update: RuntimeUpdate) -> RuntimeView:
    """RuntimeUpdate → RuntimeView（allowed_commands 排序后输出，保证稳定顺序）。"""
    state = update.state
    return RuntimeView(
        session_id=session_id,
        stage=state.stage,
        phase=state.phase,
        interaction=update.interaction,
        allowed_commands=sorted(update.allowed_commands, key=lambda c: c.value),
        status=update.status,
        event_count=state.event_count,
        head_event_id=state.head_event_id,
        character_names=[c.name for c in state.characters],
        player_role=state.player_role,
        stage2_ending_confirmed=state.stage2_ending_confirmed,
        stage3_goal=state.stage3_goal,
    )


def make_error(
    code: ErrorCode,
    message: str,
    *,
    retryable: bool = False,
    details: dict[str, Any] | None = None,
    error_id: str | None = None,
) -> ErrorEnvelope:
    """构造对外错误 envelope（cause/stack 永不进入 envelope，由诊断层写日志）。"""
    return ErrorEnvelope(
        error_id=error_id if error_id is not None else str(uuid.uuid4()),
        code=code,
        message=message,
        retryable=retryable,
        details=details or {},
    )
