"""workflow 运行器：图执行 + 进度投影（issue #28）。

- 执行经 `graph.astream(..., stream_mode="updates", version="v2")`：
  每个节点/超步产出一个 updates 事件（research doc §3.7 已验证形态），
  runner 把节点级 delta 投影为 contracts.generation 的进度快照。
- 进度落库不进图状态：`progress_sink` 回调由 ScriptLibrary 注入
  （写 script_generations 行）；测试可注入内存收集器。
- checkpointer 由调用方注入：生产 AsyncPostgresSaver，测试 MemorySaver。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.types import Command

from app.contracts.generation import (
    DoubterEvent,
    GenerationNode,
    GenerationNodeStatus,
    GenerationProgress,
    GenerationStatus,
    NodeProgress,
)
from app.domain.generation.workflow.graph import build_workflow
from app.domain.generation.workflow.nodes import MATERIALS_GATE_NODE, WorkflowNodes
from app.domain.generation.workflow.state import WorkflowState

ProgressSink = Callable[[GenerationProgress], Awaitable[None]]

# 图节点 → 对外契约节点（人物并行的两步都归 design_characters）
_NODE_MAP: dict[str, GenerationNode] = {
    "collect_materials": GenerationNode.COLLECT_MATERIALS,
    "verify_materials": GenerationNode.VERIFY_MATERIALS,
    # 闸门节点的恢复 delta（directives）归入素材考证节点（进度语义）
    MATERIALS_GATE_NODE: GenerationNode.VERIFY_MATERIALS,
    "divide_events": GenerationNode.DIVIDE_EVENTS,
    "design_characters": GenerationNode.DESIGN_CHARACTERS,
    "design_one_character": GenerationNode.DESIGN_CHARACTERS,
    "merge_characters": GenerationNode.DESIGN_CHARACTERS,
    "write_script": GenerationNode.WRITE_SCRIPT,
    "final_audit": GenerationNode.FINAL_AUDIT,
}

_NODE_ORDER: list[GenerationNode] = [
    GenerationNode.COLLECT_MATERIALS,
    GenerationNode.VERIFY_MATERIALS,
    GenerationNode.DIVIDE_EVENTS,
    GenerationNode.DESIGN_CHARACTERS,
    GenerationNode.WRITE_SCRIPT,
    GenerationNode.FINAL_AUDIT,
]


class WorkflowRunner:
    """执行 workflow 并把 updates 事件流投影为 GenerationProgress。

    进度状态机：初始除 collect_materials 外全部 pending；线性节点完成时
    置 succeeded 并把下一节点置 running；doubter reject 记 DoubterEvent
    并把上游节点置 rejected（重跑时再转 running→succeeded）；教师闸门
    （materials_gate）触发时整体置 awaiting_review（#34）。
    """

    def __init__(
        self,
        nodes: WorkflowNodes,
        *,
        checkpointer: BaseCheckpointSaver | None = None,
        progress_sink: ProgressSink | None = None,
        doubter_events: list[DoubterEvent] | None = None,
    ) -> None:
        self._graph = build_workflow(nodes, checkpointer=checkpointer)
        self._sink = progress_sink
        self._nodes: dict[GenerationNode, NodeProgress] = {}
        self._doubter_events: list[DoubterEvent] = list(doubter_events or [])
        self._status = GenerationStatus.RUNNING
        self._dirty = False
        self._interrupted = False
        self._character_detail = ""
        nodes.set_progress_hook(self._on_progress)

    def snapshot(self) -> GenerationProgress:
        return GenerationProgress(
            status=self._status,
            nodes=[
                self._nodes.get(
                    n,
                    NodeProgress(node=n, status=GenerationNodeStatus.PENDING),
                )
                for n in _NODE_ORDER
            ],
            doubter_events=list(self._doubter_events),
            error=None,
            updated_at=datetime.now(UTC),
        )

    def _set(
        self,
        node: GenerationNode,
        status: GenerationNodeStatus,
        *,
        detail: str | None = None,
    ) -> None:
        current = self._nodes.get(node)
        keep = current.detail if current is not None else None
        self._nodes[node] = NodeProgress(node=node, status=status, detail=detail or keep)
        self._dirty = True

    async def _on_progress(self, node_key: str, detail: str) -> None:
        """节点内子进度（执行中推送）：更新 detail 并即时落库，前端轮询可见。"""
        contract = _NODE_MAP.get(node_key)
        if contract is None or self._sink is None:
            return
        self._set(contract, GenerationNodeStatus.RUNNING, detail=detail)
        await self._sink(self.snapshot())
        self._dirty = False

    async def _on_update(self, node_name: str, delta: dict[str, Any]) -> None:
        contract = _NODE_MAP.get(node_name)
        if contract is None:
            return

        if node_name == "design_one_character":
            profiles = delta.get("character_profiles") or []
            name = getattr(profiles[0], "name", "?") if profiles else "?"
            self._character_detail = f"已生成人物设定：{name}"
            self._set(
                GenerationNode.DESIGN_CHARACTERS,
                GenerationNodeStatus.RUNNING,
                detail=self._character_detail,
            )
            return

        if node_name == "merge_characters":
            merged = delta.get("merged_profiles") or []
            self._set(
                GenerationNode.DESIGN_CHARACTERS,
                GenerationNodeStatus.SUCCEEDED,
                detail=f"共 {len(merged)} 位主要人物",
            )
            self._set(GenerationNode.WRITE_SCRIPT, GenerationNodeStatus.RUNNING)
            return

        # 线性节点：本节点自身完成；doubter 裁决决定是否打回上游
        verdict = str(
            delta.get("doubter_verdict") or delta.get("audit_verdict") or ""
        )
        reject = verdict == "reject"
        self._set(
            contract,
            GenerationNodeStatus.SUCCEEDED,
            detail="doubter 打回" if reject else None,
        )
        if verdict:
            # verify 事件用 doubter_round；audit 事件用 write_retries（= 书写轮次）
            round_no = int(delta.get("doubter_round") or 0)
            if not round_no:
                round_no = max(1, int(delta.get("write_retries") or 0))
            self._doubter_events.append(
                DoubterEvent(
                    node=contract,
                    verdict=verdict,
                    issues=[
                        str(i)
                        for i in delta.get("doubter_issues")
                        or delta.get("audit_issues")
                        or []
                    ],
                    round=round_no,
                )
            )
        if not reject:
            idx = _NODE_ORDER.index(contract)
            if idx + 1 < len(_NODE_ORDER):
                self._set(_NODE_ORDER[idx + 1], GenerationNodeStatus.RUNNING)
            return

        upstream = (
            GenerationNode.WRITE_SCRIPT
            if contract == GenerationNode.FINAL_AUDIT
            else GenerationNode.COLLECT_MATERIALS
        )
        self._set(
            upstream,
            GenerationNodeStatus.REJECTED,
            detail="doubter 打回，重做中",
        )

    async def run(self, state: WorkflowState, *, thread_id: str) -> dict[str, Any]:
        """执行图并收集终态；打回耗尽（fail 节点）时异常上抛由调用方兜底。"""
        self._set(GenerationNode.COLLECT_MATERIALS, GenerationNodeStatus.RUNNING)
        if self._sink is not None:
            await self._sink(self.snapshot())
        return await self._consume(state, thread_id)

    async def resume(self, *, thread_id: str, directives: list[str]) -> dict[str, Any]:
        """教师闸门恢复（#34）：从 checkpointer 断点继续，指令并入下游输入。"""
        # 恢复时进度从闸门前状态接续：素材/考证已完成，划分即将开始
        self._set(GenerationNode.COLLECT_MATERIALS, GenerationNodeStatus.SUCCEEDED)
        self._set(GenerationNode.VERIFY_MATERIALS, GenerationNodeStatus.SUCCEEDED)
        self._set(GenerationNode.DIVIDE_EVENTS, GenerationNodeStatus.RUNNING)
        if self._sink is not None:
            await self._sink(self.snapshot())
        return await self._consume(Command(resume=directives), thread_id)

    async def _consume(self, graph_input: Any, thread_id: str) -> dict[str, Any]:
        config = {"configurable": {"thread_id": thread_id}}
        final: dict[str, Any] = {}
        async for part in self._graph.astream(
            graph_input, config, stream_mode="updates", version="v2"
        ):
            data = part.get("data") if isinstance(part, dict) else None
            if not data:
                continue
            for node_name, delta in data.items():
                if node_name == "__interrupt__":
                    # 教师闸门触发：图停在闸门节点，本次流结束
                    self._interrupted = True
                    self._status = GenerationStatus.AWAITING_REVIEW
                    self._set(
                        GenerationNode.DIVIDE_EVENTS,
                        GenerationNodeStatus.PENDING,
                        detail="等待教师审阅",
                    )
                    if self._sink is not None:
                        await self._sink(self.snapshot())
                    continue
                if not isinstance(delta, dict):
                    continue
                final.update(delta)
                await self._on_update(node_name, delta)
                if self._dirty and self._sink is not None:
                    self._dirty = False
                    await self._sink(self.snapshot())
        if self._interrupted:
            self._status = GenerationStatus.AWAITING_REVIEW
        else:
            self._status = (
                GenerationStatus.SUCCEEDED if final.get("package") is not None
                else GenerationStatus.FAILED
            )
        if self._sink is not None:
            await self._sink(self.snapshot())
        return final
