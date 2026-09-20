"""剧本生成 workflow 的集中 prompt 模板（issue #28 / #27 spec 决策）。

- 每个节点一个模块，导出 `PROMPT_VERSION` 与 `build_user_message(...)`；
  system prompt 为模块常量。节点按模块加载，只传变量——不再在业务代码里
  内联 prompt 字符串。
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
)

__all__ = ["character_design", "collect_materials", "divide_events", "doubter"]
