"""剧本生成 workflow 包（issue #28 骨架）。

- `graph.build_workflow`：LangGraph 装配（素材收集 → doubter → 事件划分 →
  人物并行 → 剧本书写 → 总审）。
- `WorkflowRunner`：图执行 + 进度投影（contracts.generation）。
- `WorkflowNodes`：节点实现（直接调用现有 LLMService，prompt 走 app/prompts/）。
"""

from app.generation.workflow.nodes import (
    MAX_DOUBTER_ROUNDS,
    MAX_MAIN_CHARACTERS,
    MAX_WRITE_RETRIES,
    WorkflowNodes,
)
from app.generation.workflow.runner import WorkflowRunner
from app.generation.workflow.state import WorkflowState, initial_state

__all__ = [
    "MAX_DOUBTER_ROUNDS",
    "MAX_MAIN_CHARACTERS",
    "MAX_WRITE_RETRIES",
    "WorkflowNodes",
    "WorkflowRunner",
    "WorkflowState",
    "initial_state",
]
