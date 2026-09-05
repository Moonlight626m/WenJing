"""确定性假 Agent LLM（#5 fake-backed 竖切的默认适配器）。

未配置真实 provider API key 时，运行时（角色提议/反应/验证）使用本实现，
保证竖切端到端可跑、行为可复现。#12 接入真实 LLM 后仅替换注入对象。
"""

from __future__ import annotations

from typing import TypeAlias

Message: TypeAlias = dict[str, str]

DEFAULT_PROPOSAL = "我提议按照课文情节继续推进"
DEFAULT_REACTION = "我平静地回应你的选择。"


class DeterministicAgentLLM:
    """零网络依赖的确定性 LLM：验证 pass、提议/反应返回固定文案。"""

    def __init__(
        self,
        *,
        proposal_text: str = DEFAULT_PROPOSAL,
        react_text: str = DEFAULT_REACTION,
    ) -> None:
        self._proposal_text = proposal_text
        self._react_text = react_text
        self.call_count = 0

    async def chat(self, messages: list[Message], *, session_id: str = "") -> str:
        self.call_count += 1
        user = messages[-1]["content"] if messages else ""
        if "验证 Agent" in user or "你是验证" in user:
            return "pass"
        if "react" in user:
            return self._react_text
        return self._proposal_text
