"""剧本生成 workflow 进度契约（issue #28 / #27 spec）。

进度模型对外只描述「每节点状态 + doubter 事件 + 总体状态」：
完整中间产物（素材集/划分草稿/人物设定草稿）是 backend 内部类型，不进契约。
LangGraph 图状态（checkpointer）负责可恢复性，本契约负责教师端观测。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import Field

from app.contracts.base import VersionedContract


class GenerationStatus(StrEnum):
    """一次生成尝试的总体状态。

    awaiting_review 为教师闸门预留（#34）：流水线停在闸门等审阅。
    """

    IDLE = "idle"
    RUNNING = "running"
    AWAITING_REVIEW = "awaiting_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class GenerationNode(StrEnum):
    """workflow 节点（与 generation/workflow/graph.py 的图拓扑对齐）。"""

    COLLECT_MATERIALS = "collect_materials"
    VERIFY_MATERIALS = "verify_materials"
    DIVIDE_EVENTS = "divide_events"
    DESIGN_CHARACTERS = "design_characters"
    WRITE_SCRIPT = "write_script"
    FINAL_AUDIT = "final_audit"


class GenerationNodeStatus(StrEnum):
    """节点级状态：rejected 表示被 doubter 打回（上游会重做）。"""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    FAILED = "failed"


class NodeProgress(VersionedContract):
    """单个 workflow 节点的进度投影。"""

    node: GenerationNode
    status: GenerationNodeStatus
    detail: str | None = None


class DoubterIssue(VersionedContract):
    """doubter 单条问题：可定位、可执行（Self-Refine 心智，spec 裁决）。

    - field：产物中的字段定位（如 scenes[2].beats[4].description）；
    - severity：must-fix ≥1 条即 reject；nice-to-fix 不触发打回；
    - evidence：判定依据（原文依据摘要中的对应条目/摘录）。
    """

    field: str = Field(min_length=1)
    quote: str = ""
    category: Literal["人物事实", "事件顺序", "编造情节", "篡改关键事实"]
    evidence: str = ""
    severity: Literal["must_fix", "nice_to_fix"]
    suggestion: str = ""


class DoubterVerdict(VersionedContract):
    """doubter 产物契约（素材质检 / 终审两处复用）：裁决 + 结构化问题清单。"""

    verdict: str = Field(pattern=r"^(pass|reject)$")
    issues: list[DoubterIssue] = Field(default_factory=list)


class DoubterEvent(VersionedContract):
    """doubter 裁决记录：打回时带逐条问题（教师端可见）。"""

    node: GenerationNode
    verdict: str = Field(pattern=r"^(pass|reject)$")
    issues: list[str] = Field(default_factory=list)
    round: int = Field(ge=1, le=3, default=1)


class GenerationProgress(VersionedContract):
    """生成进度：长时间生成过程不是黑盒（进度由 script_generations 落库）。"""

    status: GenerationStatus
    nodes: list[NodeProgress] = Field(default_factory=list)
    doubter_events: list[DoubterEvent] = Field(default_factory=list)
    error: str | None = None
    updated_at: datetime | None = None


__all__ = [
    "GenerationStatus",
    "GenerationNode",
    "GenerationNodeStatus",
    "NodeProgress",
    "DoubterIssue",
    "DoubterVerdict",
    "DoubterEvent",
    "GenerationProgress",
]
