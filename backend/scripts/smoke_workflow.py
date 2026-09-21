"""真实 LLM 连通冒烟：完整跑通生成 workflow（issue #28 验收）。

用法（需 WENJING_LLM_API_KEY，且本地 PG 已迁移）：
    cd backend && uv run python -m scripts.smoke_workflow [课文文本文件]

无 key 时打印提示并以非零码退出（CI 不依赖此脚本）。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from app.contracts.material import MaterialInput, MaterialSource
from app.infrastructure.config import get_settings

DEFAULT_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)


def _analyze(text: str):
    from app.domain.content.pipeline import ContentPipeline

    return ContentPipeline().analyze(
        MaterialInput(source=MaterialSource.PASTE, raw_text=text)
    )


async def main() -> int:
    settings = get_settings()
    if not settings.llm_api_key:
        print("smoke skipped: WENJING_LLM_API_KEY 未配置")
        return 1

    from app.domain.generation.workflow import (
        WorkflowNodes,
        WorkflowRunner,
        initial_state,
    )
    from app.infrastructure.llm.factory import ModelServiceFactory

    text = (
        Path(sys.argv[1]).read_text(encoding="utf-8")
        if len(sys.argv) > 1
        else DEFAULT_TEXT
    )
    analysis = _analyze(text)
    llm = ModelServiceFactory.build(settings.llm_model_config())
    nodes = WorkflowNodes(llm, model_name=settings.llm_model)
    runner = WorkflowRunner(nodes)  # 无 checkpointer：冒烟只验证连通与产出
    state = initial_state(
        script_id=0,
        session_id="smoke-workflow",
        analysis=analysis,
        web_evidence=[],
    )
    final = await runner.run(state, thread_id="smoke-workflow")
    package = final.get("package")
    if package is None:
        print("smoke FAILED: 未产出 ScriptPackage")
        return 2
    snap = runner.snapshot()
    print(f"smoke OK: {package.title} / {len(package.scenes)} 场景 / "
          f"{len(package.characters)} 人物")
    for node in snap.nodes:
        detail = f" ({node.detail})" if node.detail else ""
        print(f"  {node.node.value}: {node.status.value}{detail}")
    for ev in snap.doubter_events:
        print(f"  doubter[{ev.round}] {ev.node.value}: {ev.verdict}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
