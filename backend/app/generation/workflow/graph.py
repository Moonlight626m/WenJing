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
- 闸门（#34）：在 divide_events / merge_characters 产物落库后以
  `interrupt()` 实现暂停/恢复；checkpointer（AsyncPostgresSaver）持久化。
"""

from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from app.generation.workflow.nodes import WorkflowNodes
from app.generation.workflow.state import WorkflowState


def build_workflow(
    nodes: WorkflowNodes,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """装配并编译生成 workflow；checkpointer 由调用方注入（测试传 MemorySaver）。"""
    graph = StateGraph(WorkflowState)
    graph.add_node("collect_materials", nodes.collect_materials)
    graph.add_node("verify_materials", nodes.verify_materials)
    graph.add_node("divide_events", nodes.divide_events)
    graph.add_node("design_one_character", nodes.design_one_character)
    graph.add_node("merge_characters", nodes.merge_characters)
    graph.add_node("write_script", nodes.write_script)
    graph.add_node("final_audit", nodes.final_audit)
    graph.add_node("fail", nodes.fail)

    graph.add_edge(START, "collect_materials")
    graph.add_edge("collect_materials", "verify_materials")
    graph.add_conditional_edges(
        "verify_materials",
        nodes.route_after_verify,
        {
            "collect_materials": "collect_materials",
            "divide_events": "divide_events",
            "fail": "fail",
        },
    )
    # 人物并行：divide_events 后经条件边 Send 出 N 个分支（join 靠 reducer + 边汇聚）
    graph.add_conditional_edges("divide_events", nodes.design_characters)
    graph.add_edge("design_one_character", "merge_characters")
    graph.add_edge("merge_characters", "write_script")
    graph.add_edge("write_script", "final_audit")
    graph.add_conditional_edges(
        "final_audit",
        nodes.route_after_audit,
        {"write_script": "write_script", "fail": "fail", "END": END},
    )
    graph.add_edge("fail", END)
    return graph.compile(checkpointer=checkpointer)
