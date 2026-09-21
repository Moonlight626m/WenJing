"""workflow 图状态 schema（issue #28）。

- TypedDict + Annotated reducers（research doc §5 建议：避免 Pydantic State
  坏输入污染 checkpointer thread 的坑）。
- 只有跨 Send 分支汇聚的通道需要 reducer（character_profiles 累加），
  其余通道线性覆写即可。
- 图状态是运行时机制，不对外；对外进度由 runner 从 updates 事件投影。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from app.contracts.content import TextAnalysis
from app.contracts.material import WebEvidence
from app.contracts.script import CharacterProfile, ScriptPackage
from app.domain.generation.workflow.types import EventDivisionDraft, MaterialDossier


class WorkflowState(TypedDict, total=False):
    """图状态通道。Send 并行分支各自写 character_profiles（累加）。"""

    # ===== 输入（运行前注入）=====
    script_id: int
    session_id: str
    analysis: TextAnalysis
    # JSON-safe dict（WebEvidence.model_dump(mode="json")）：HttpUrl 无法被
    # langgraph checkpointer 的 msgpack 序列化，模型入 state 会炸闸门 interrupt。
    # 读取用 `state_web_evidence()` 还原成契约模型。
    web_evidence: list[dict[str, Any]]
    # 教师指导指令（#34 闸门注入；骨架恒空）
    directives: list[str]
    # 终审闸门恢复后的路由标记（final_gate → route_after_final_gate）
    gate_action: str

    # ===== 节点产物 =====
    dossier: MaterialDossier | None
    division: EventDivisionDraft | None
    # Send fan-out 产物通道：每人物分支追加一个 profile，join 时已聚合
    character_profiles: Annotated[list[CharacterProfile], operator.add]
    merged_profiles: list[CharacterProfile]
    package: ScriptPackage | None
    write_telemetry: dict

    # ===== doubter 打回回路 =====
    doubter_verdict: str
    doubter_issues: list[str]
    doubter_round: int
    doubter_feedback: str | None

    # ===== final_audit 打回回路 =====
    audit_verdict: str
    audit_issues: list[str]
    write_retries: int
    audit_feedback: str | None


def initial_state(
    *,
    script_id: int,
    session_id: str,
    analysis: TextAnalysis,
    web_evidence: list[WebEvidence],
    directives: list[str] | None = None,
) -> WorkflowState:
    return WorkflowState(
        script_id=script_id,
        session_id=session_id,
        analysis=analysis,
        web_evidence=[e.model_dump(mode="json") for e in web_evidence],
        directives=list(directives or []),
        character_profiles=[],
        doubter_round=0,
        write_retries=0,
    )


def state_web_evidence(state: WorkflowState) -> list[WebEvidence]:
    """从 state 通道还原 `WebEvidence`（通道内是 JSON-safe dict，见类型注释）。"""
    return [
        e if isinstance(e, WebEvidence) else WebEvidence.model_validate(e)
        for e in state.get("web_evidence") or []
    ]
