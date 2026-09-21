"""剧本生成 workflow 图（issue #28 骨架）。

拓扑（#27 spec 决策的骨架版）：
  START → collect_materials → verify_materials(doubter)
        ├ pass → divide_events
        │         → design_characters（条件边返回 Send，人物并行）
        │           → design_one_character×N → merge_characters(join)
        │           → write_script → final_audit(doubter 总审)
        │             ├ pass → END
        │             └ reject → write_script（≤MAX_WRITE_RETRIES）→ fail
        ├ reject → collect_materials（带打回意见，≤MAX_DOUBTER_ROUNDS）
        └ 耗尽 → fail（显式失败终点，异常上抛）

- Send 并行：design_characters 经 add_conditional_edges 发出 N 个
  `design_one_character` 分支，character_profiles 通道以 add reducer 聚合，
  merge_characters 是 join（super-step 屏障等待全部分支）。
- 闸门（#34）：启用 materials_gate 时，素材考证通过后在
  `materials_gate` 节点 `interrupt()` 暂停，教师审阅后以
  `Command(resume=directives)` 恢复；checkpointer（AsyncPostgresSaver）持久化。
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Callable
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import END, START, StateGraph

from app.domain.generation.workflow.nodes import MATERIALS_GATE_NODE, WorkflowNodes
from app.domain.generation.workflow.state import WorkflowState

_L = logging.getLogger("wenjing.generation.workflow")


def _session_id(candidate: Any) -> str:
    return (
        str(candidate.get("session_id", ""))
        if isinstance(candidate, dict)
        else ""
    )


def _logged(node_name: str) -> Callable[[Callable], Callable]:
    """节点日志装饰器：记录 start / done / failed 与耗时（结构化字段）。"""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        async def wrapper(candidate: Any, *args: Any, **kwargs: Any) -> Any:
            sid = _session_id(candidate)
            _L.info(
                f"[script-gen][{node_name}] start",
                extra={"session_id": sid},
            )
            started = time.monotonic()
            try:
                out = await fn(candidate, *args, **kwargs)
            except GraphInterrupt:
                # 教师闸门暂停（#34）：等待恢复，不是失败
                _L.info(
                    f"[script-gen][{node_name}] paused(teacher gate)",
                    extra={"session_id": sid},
                )
                raise
            except BaseException as exc:  # noqa: BLE001 - 记录后原样重抛
                _L.error(
                    f"[script-gen][{node_name}] failed",
                    extra={
                        "session_id": sid,
                        "duration_ms": int((time.monotonic() - started) * 1000),
                        "wj_extra": {"error_type": type(exc).__name__},
                    },
                )
                raise
            _L.info(
                f"[script-gen][{node_name}] done",
                extra={
                    "session_id": sid,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                },
            )
            return out

        return wrapper

    return deco


def _logged_route(name: str) -> Callable[[Callable], Callable]:
    """条件边路由日志：记录 verify/audit 的裁决走向与轮次。"""

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(state: dict[str, Any]) -> str:
            target = fn(state)
            sid = _session_id(state)
            dround = state.get("doubter_round", 0)
            retries = state.get("write_retries", 0)
            detail = ""
            if dround:
                detail += f" doubter_round={dround}"
            if retries:
                detail += f" write_retries={retries}"
            _L.info(
                f"[script-gen][{name}] ->{target}{detail}",
                extra={
                    "session_id": sid,
                    "wj_extra": {
                        "node_to": target,
                        "doubter_round": dround,
                        "write_retries": retries,
                    },
                },
            )
            return target

        return wrapper

    return deco


def _logged_send(fn: Callable) -> Callable:
    """人物 fan-out 日志：记录派发数量与人物名。"""

    @functools.wraps(fn)
    def wrapper(state: dict[str, Any]) -> list[Any]:
        sends = fn(state)
        names = []
        for s in sends:
            payload = (
                getattr(s, "payload", None)
                or getattr(s, "arg", None)  # langgraph >=1.2: Send.arg
            )
            if isinstance(payload, dict):
                names.append(payload.get("name", "?"))
        _L.info(
            "[script-gen][design_characters] fanout=%d names=%s",
            len(names),
            ",".join(str(n) for n in names),
            extra={"session_id": _session_id(state)},
        )
        return sends

    return wrapper


def build_workflow(
    nodes: WorkflowNodes,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """装配并编译生成 workflow；checkpointer 由调用方注入（测试传 MemorySaver）。"""
    graph = StateGraph(WorkflowState)
    gate_on = nodes.gate_enabled
    graph.add_node("collect_materials", _logged("collect_materials")(nodes.collect_materials))
    graph.add_node("verify_materials", _logged("verify_materials")(nodes.verify_materials))
    if gate_on:
        # #34 教师闸门：素材考证通过后暂停，interrupt() 等教师恢复
        graph.add_node(MATERIALS_GATE_NODE, _logged(MATERIALS_GATE_NODE)(nodes.materials_gate))
    graph.add_node("divide_events", _logged("divide_events")(nodes.divide_events))
    graph.add_node(
        "design_one_character",
        _logged("design_one_character")(nodes.design_one_character),
    )
    graph.add_node("merge_characters", _logged("merge_characters")(nodes.merge_characters))
    graph.add_node("write_script", _logged("write_script")(nodes.write_script))
    graph.add_node("final_audit", _logged("final_audit")(nodes.final_audit))
    graph.add_node("fail", _logged("fail")(nodes.fail))

    graph.add_edge(START, "collect_materials")
    graph.add_edge("collect_materials", "verify_materials")
    after_verify = MATERIALS_GATE_NODE if gate_on else "divide_events"
    graph.add_conditional_edges(
        "verify_materials",
        _logged_route("verify_materials")(nodes.route_after_verify),
        {
            "collect_materials": "collect_materials",
            after_verify: after_verify,
            "fail": "fail",
        },
    )
    if gate_on:
        graph.add_edge(MATERIALS_GATE_NODE, "divide_events")
    # 人物并行：divide_events 后经条件边 Send 出 N 个分支（join 靠 reducer + 边汇聚）
    graph.add_conditional_edges("divide_events", _logged_send(nodes.design_characters))
    graph.add_edge("design_one_character", "merge_characters")
    graph.add_edge("merge_characters", "write_script")
    graph.add_edge("write_script", "final_audit")
    graph.add_conditional_edges(
        "final_audit",
        _logged_route("final_audit")(nodes.route_after_audit),
        {"write_script": "write_script", "fail": "fail", "END": END},
    )
    graph.add_edge("fail", END)
    return graph.compile(checkpointer=checkpointer)
