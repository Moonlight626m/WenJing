"""LLM 端口（domain 持有的抽象，实现由 infrastructure 提供）。

- `LLMService`（Protocol）：统一的 `chat(messages, *, session_id)` 入口，返回文本。
- `TokenUsage`：provider 回报的真实 token 用量（#22）；不可得时为 None。
- domain（游戏运行时/剧本生成）只依赖本端口，具体 provider 适配器注入到
  `infrastructure/llm/`（ChatLLMService / ModelServiceFactory / fake）。

设计约束（design_00 D7）：单例会所，每轮每 Agent 一次 LLM 调用；
错误统一包装为 `codes.LLM_CALL_FAILED`。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, TypeAlias, runtime_checkable

from app.contracts.enums import UsagePurpose

Message: TypeAlias = dict[str, str]  # {"role": ..., "content": ...}


@dataclass(frozen=True)
class TokenUsage:
    """provider 回报的真实 token 用量（#22）；不可得时为 None。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@runtime_checkable
class LLMService(Protocol):
    """可注入的 LLM 服务接口。

    `purpose` 标识调用来源（stage1/agent/verify），供用量计量（#22）分类；
    纯传输实现可忽略该参数。实现若提供 `chat_with_usage`（返回真实 token 用量），
    计量装饰器会优先采信，否则回落到估算。
    """

    async def chat(
        self,
        messages: list[Message],
        *,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> str: ...
