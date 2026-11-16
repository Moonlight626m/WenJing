"""workflow 运行器：图执行 + 进度投影（issue #28）。

- 执行经 `graph.astream(..., stream_mode="updates", version="v2")`：
  每个节点/超步产出一个 updates 事件（research doc §3.7 已验证形态），
  runner 把节点级 delta 投影为 contracts.generation 的进度快照。
- 进度落库不进图状态：`progress_sink` 回调由 ScriptLibrary 注入
  （写 script_generations 行）；测试可注入内存收集器。
- checkpointer 由调用方注入：生产 AsyncPostgresSaver，测试 MemorySaver。
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
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
from app.domain.generation.workflow.nodes import (
    FINAL_GATE_NODE,
    MATERIALS_GATE_NODE,
    PRE_WRITE_GATE_NODE,
    WorkflowNodes,
)
from app.domain.generation.workflow.state import WorkflowState

logger = logging.getLogger("wenjing.generation.workflow")

ProgressSink = Callable[[GenerationProgress], Awaitable[None]]
# 闸门审阅载荷落库回调：在 awaiting_review 快照广播**之前**调用，订阅方收到
# 终态帧后立即回读详情即可拿到 review（否则窗口内读到 None，面板显示空素材）。
ReviewSink = Callable[[dict[str, Any] | None], Awaitable[None]]

# 图节点 → 对外契约节点（人物并行的两步都归 design_characters）
_NODE_MAP: dict[str, GenerationNode] = {
    "collect_materials": GenerationNode.COLLECT_MATERIALS,
    "verify_materials": GenerationNode.VERIFY_MATERIALS,
    # 闸门节点的恢复 delta（directives）归入上游节点（进度语义）
    MATERIALS_GATE_NODE: GenerationNode.VERIFY_MATERIALS,
    PRE_WRITE_GATE_NODE: GenerationNode.DESIGN_CHARACTERS,
    "divide_events": GenerationNode.DIVIDE_EVENTS,
    "design_characters": GenerationNode.DESIGN_CHARACTERS,
    "design_one_character": GenerationNode.DESIGN_CHARACTERS,
    "merge_characters": GenerationNode.DESIGN_CHARACTERS,
    "write_script": GenerationNode.WRITE_SCRIPT,
    "write_dialogue": GenerationNode.WRITE_DIALOGUE,
    "final_audit": GenerationNode.FINAL_AUDIT,
    FINAL_GATE_NODE: GenerationNode.FINAL_AUDIT,
    "design_exploration": GenerationNode.DESIGN_EXPLORATION,
    "design_assets": GenerationNode.DESIGN_ASSETS,
}

_NODE_ORDER: list[GenerationNode] = [
    GenerationNode.COLLECT_MATERIALS,
    GenerationNode.VERIFY_MATERIALS,
    GenerationNode.DIVIDE_EVENTS,
    GenerationNode.DESIGN_CHARACTERS,
    GenerationNode.WRITE_SCRIPT,
    GenerationNode.WRITE_DIALOGUE,
    GenerationNode.FINAL_AUDIT,
    GenerationNode.DESIGN_EXPLORATION,
    GenerationNode.DESIGN_ASSETS,
]

_GATE_NODES = frozenset({MATERIALS_GATE_NODE, PRE_WRITE_GATE_NODE, FINAL_GATE_NODE})


def _interrupt_value(delta: Any) -> dict[str, Any] | None:
    """updates 流里 `__interrupt__` 的载荷：tuple[Interrupt] → Interrupt.value。"""
    if isinstance(delta, (list, tuple)) and delta:
        value = getattr(delta[0], "value", delta[0])
        return value if isinstance(value, dict) else None
    return None

# 打回回路没有业务轮次上限，图递归上限是唯一的死循环兜底：一次完整生成约 15 个
# super-step，10000 远大于任何真实重做次数（LangGraph 默认 25 会让第 3 轮打回
# 附近就抛 GraphRecursionError）。
WORKFLOW_RECURSION_LIMIT = 10_000


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
        review_sink: ReviewSink | None = None,
        doubter_events: list[DoubterEvent] | None = None,
    ) -> None:
        self._graph = build_workflow(nodes, checkpointer=checkpointer)
        self._sink = progress_sink
        self._review_sink = review_sink
        self._teacher_gates = nodes.gate_enabled
        self._nodes: dict[GenerationNode, NodeProgress] = {}
        self._doubter_events: list[DoubterEvent] = list(doubter_events or [])
        self._status = GenerationStatus.RUNNING
        self._dirty = False
        self._interrupted = False
        self._review: dict[str, Any] | None = None
        self._character_detail = ""
        nodes.set_progress_hook(self._on_progress)

    @property
    def review(self) -> dict[str, Any] | None:
        """闸门暂停时给教师的审阅载荷（interrupt 值，JSON-safe dict）。"""
        return self._review

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

        if node_name in _GATE_NODES:
            # 闸门节点的 delta 只表示「教师恢复」，下一步的投影由 resume() 负责。
            # 走通用「推进下一个节点」会把已完成的节点重新置 running——终审之后
            # 图上还有 design_exploration/design_assets，恢复后它们会被再次
            # 标成 running 且再无节点收尾（现象：探索地图永久转圈）。
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
            self._set(
                GenerationNode.WRITE_SCRIPT,
                GenerationNodeStatus.RUNNING if not self._teacher_gates
                else GenerationNodeStatus.PENDING,
            )
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
            # verify 事件用 doubter_round；audit 事件用 write_retries（= 书写轮次，
            # 含教师终审打回轮）
            round_no = int(delta.get("doubter_round") or 0)
            if not round_no:
                round_no = max(1, int(delta.get("write_retries") or 0))
            self._doubter_events.append(
                DoubterEvent(
                    node=contract,
                    verdict=verdict,
                    # 结构化问题原样透传（教师端分块渲染）；规则校验是纯字符串
                    issues=list(
                        delta.get("doubter_issues")
                        or delta.get("audit_issues")
                        or []
                    ),
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

    def seed_nodes(self, nodes: list[NodeProgress]) -> None:
        """从上一 attempt 落库快照恢复节点状态（闸门恢复，进度不归零）。

        闸门 pause→resume 换了 runner 实例：不播种的话闸门之前的节点会全回
        pending，前端表现为「进到下一阶段，之前阶段的勾全消失」。resume()
        随后按闸门位置覆盖「下一步」节点的运行态，两者叠加即完整接续。
        """
        for progress in nodes:
            self._nodes[progress.node] = progress

    async def run(self, state: WorkflowState, *, thread_id: str) -> dict[str, Any]:
        """执行图并收集终态；节点异常时上抛由调用方兜底。"""
        self._set(GenerationNode.COLLECT_MATERIALS, GenerationNodeStatus.RUNNING)
        if self._sink is not None:
            await self._sink(self.snapshot())
        try:
            return await self._consume(state, thread_id)
        except GraphInterrupt:
            # 闸门暂停不是失败（正常路径由 __interrupt__ 分支投影）
            raise
        except Exception:
            await self._mark_running_failed()
            raise

    async def resume(
        self, *, thread_id: str, resume_payload: Any, gate: str = "materials"
    ) -> dict[str, Any]:
        """教师闸门恢复（#34）：从 checkpointer 断点继续。

        `resume_payload` 是闸门恢复载荷（GenerationResumeRequest 形状的 dict；
        兼容旧列表指令）。`gate` 是暂停位置（materials/pre_write/final，
        调用方从 attempt 落库的审阅载荷读取），决定进度接续投影。
        """
        # 恢复时重写「下一步」节点的 detail：`_set` 在 detail=None 时会保留旧值，
        # 不覆盖的话闸门暂停时写的「等待教师审阅」会一直挂到节点跑完（前端误以为
        # 还在等审阅，实际没有任何待审界面）。文案取「已通过审定」这类完成后
        # 仍成立的措辞——detail 在节点成功后同样会保留。
        action = (
            str(resume_payload.get("action") or "approve")
            if isinstance(resume_payload, dict)
            else "approve"
        )
        if gate == "pre_write":
            self._set(GenerationNode.DIVIDE_EVENTS, GenerationNodeStatus.SUCCEEDED)
            self._set(GenerationNode.DESIGN_CHARACTERS, GenerationNodeStatus.SUCCEEDED)
            self._set(
                GenerationNode.WRITE_SCRIPT,
                GenerationNodeStatus.RUNNING,
                detail="教师已通过人物与场景审定",
            )
        elif gate == "final":
            self._set(GenerationNode.WRITE_SCRIPT, GenerationNodeStatus.SUCCEEDED)
            # #48：配图在总审之后、终审闸之前，恢复时已产出
            self._set(GenerationNode.DESIGN_ASSETS, GenerationNodeStatus.SUCCEEDED)
            if action == "reject":
                # 终审打回：图上回到 write_script 重写，不能显示「已通过终审」
                self._set(
                    GenerationNode.FINAL_AUDIT,
                    GenerationNodeStatus.SUCCEEDED,
                    detail="教师打回，重写剧本",
                )
                self._set(
                    GenerationNode.WRITE_SCRIPT,
                    GenerationNodeStatus.RUNNING,
                    detail="教师打回，重写剧本",
                )
            else:
                self._set(
                    GenerationNode.FINAL_AUDIT,
                    GenerationNodeStatus.SUCCEEDED,
                    detail="教师已通过终审",
                )
        else:
            self._set(GenerationNode.COLLECT_MATERIALS, GenerationNodeStatus.SUCCEEDED)
            self._set(GenerationNode.VERIFY_MATERIALS, GenerationNodeStatus.SUCCEEDED)
            self._set(
                GenerationNode.DIVIDE_EVENTS,
                GenerationNodeStatus.RUNNING,
                detail="教师已通过素材审定",
            )
        if self._sink is not None:
            await self._sink(self.snapshot())
        try:
            return await self._consume(Command(resume=resume_payload), thread_id)
        except GraphInterrupt:
            raise
        except Exception:
            await self._mark_running_failed()
            raise

    async def _mark_running_failed(self) -> None:
        """异常退出：在途节点标红，管线图才能指出死在哪一步。

        原先只由调用方改总体状态，节点仍停在 running + 上一段 detail，
        失败现场看起来像「还在跑」。
        """
        changed = False
        for node, progress in list(self._nodes.items()):
            if progress.status != GenerationNodeStatus.RUNNING:
                continue
            self._nodes[node] = NodeProgress(
                node=node,
                status=GenerationNodeStatus.FAILED,
                detail="生成失败",
            )
            changed = True
        self._status = GenerationStatus.FAILED
        if changed and self._sink is not None:
            try:
                await self._sink(self.snapshot())
            except Exception:  # noqa: BLE001 - 落库失败不能盖掉原始异常
                logger.warning(
                    "progress sink failed while marking generation failed",
                    exc_info=True,
                )

    def _awaiting_node(self, review: dict[str, Any] | None) -> None:
        """闸门暂停时的进度投影：按闸门位置把「下一步」节点置等待态。"""
        gate = str((review or {}).get("gate", "materials"))
        if gate == "pre_write":
            self._set(
                GenerationNode.WRITE_SCRIPT,
                GenerationNodeStatus.PENDING,
                detail="等待教师审阅",
            )
        elif gate == "final":
            self._set(
                GenerationNode.FINAL_AUDIT,
                GenerationNodeStatus.SUCCEEDED,
                detail="等待教师终审",
            )
        else:
            self._set(
                GenerationNode.DIVIDE_EVENTS,
                GenerationNodeStatus.PENDING,
                detail="等待教师审阅",
            )

    async def _consume(self, graph_input: Any, thread_id: str) -> dict[str, Any]:
        config = {
            "configurable": {"thread_id": thread_id},
            "recursion_limit": WORKFLOW_RECURSION_LIMIT,
        }
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
                    self._review = _interrupt_value(delta)
                    # 先落审阅载荷再广播 awaiting_review：订阅方收到终态帧后
                    # 回读详情必须能拿到 review（顺序反了就有一段 null 窗口）
                    if self._review_sink is not None:
                        await self._review_sink(self._review)
                    self._awaiting_node(self._review)
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
            # 恢复路径：终态产物可能在上次断点前已写入 checkpoint
            # （如终审通过恢复只重放闸门节点），delta 累积器拿不到，
            # 需回读图状态补齐缺失通道。
            state_values = await self._graph.aget_state(config)
            if state_values is not None:
                for key, value in (state_values.values or {}).items():
                    final.setdefault(key, value)
            self._status = (
                GenerationStatus.SUCCEEDED if final.get("package") is not None
                else GenerationStatus.FAILED
            )
        if self._sink is not None:
            await self._sink(self.snapshot())
        return final
