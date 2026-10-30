"""剧本生成 workflow 的集中 prompt 模板（issue #28 / #27 spec 决策 → PromptMgr）。

- 每个节点一个模块，导出 `NODE` / `VERSION` / `PROMPT_VERSION` /
  `DEFAULTS`（代码默认段落）与 `build_user_message(...)`；
- prompt 文案经 PromptBundle 取值：DB 覆盖层优先，缺省回退模块 DEFAULTS
  （manager.py / defaults.py / bundle.py 为 PromptMgr 组件）；
- `PROMPT_VERSION` 逐次写入 telemetry（scripts.verification / 进度详情），
  供效果回归定位。
- 注意：`agents/fake_llm.py` 曾依赖 prompt 中的中文关键词路由，其耦合仅限
  运行时 Stage2/3 链路；生成 workflow 的测试用 tests 里按 purpose 路由的
  scripted LLM（fake 只作开发临时组件，#33 退役）。
"""

from app.domain.prompts import (
    character_design,
    collect_materials,
    divide_events,
    doubter,
    write_script,
)

__all__ = [
    "character_design",
    "collect_materials",
    "divide_events",
    "doubter",
    "write_script",
]
