"""LLM 端口（domain 持有的抽象，实现由 infrastructure 提供）。

- `LLMService`（Protocol）：统一的 `chat(messages, *, session_id)` 入口，返回文本。
- `ToolCallingLLM`（Protocol）：在 `LLMService` 之上增加 `chat_with_tools`，供
  LangChain agent 的工具调用链路（`agents/chat_model.py`）使用；实现可选，
  不支持工具调用的实现只需提供 `chat`，chat_model 会降级为无工具单轮。
- `TokenUsage`：provider 回报的真实 token 用量（#22）；不可得时为 None。
- `ToolCall` / `LLMReply`：工具调用对话的单轮回复（content + tool_calls + usage）。
- domain（游戏运行时/剧本生成）只依赖本端口，具体 provider 适配器注入到
  `infrastructure/llm/`（ChatLLMService / ModelServiceFactory / fake）。

设计约束（design_00 D7 / ADR-0004）：单例会所，每轮每 Agent 一次 LLM 调用；
工具调用 Agent 在一轮内可能往返多次（工具调用 + 最终答复），每次调用仍单独计量；
错误统一包装为 `codes.LLM_CALL_FAILED`。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, TypeAlias, runtime_checkable

from app.contracts.enums import UsagePurpose

Message: TypeAlias = dict[str, str]  # {"role": ..., "content": ...}
# 工具调用对话的消息形状：assistant 可携带 tool_calls，tool 结果带 tool_call_id。
ProviderMessage: TypeAlias = dict[str, Any]


@dataclass(frozen=True)
class TokenUsage:
    """provider 回报的真实 token 用量（#22）；不可得时为 None。"""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ToolCall:
    """模型请求调用的单个工具（OpenAI tool_call 的领域投影）。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LLMReply:
    """一轮带工具能力的模型回复：文本内容、工具调用与 token 用量。"""

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()
    usage: TokenUsage | None = None


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


@runtime_checkable
class ToolCallingLLM(Protocol):
    """可选能力：支持工具调用的 LLM 实现（LangChain agent 的工具链路依赖）。

    工具 schema 采用 OpenAI 函数调用格式；返回 `LLMReply`（含 tool_calls）。
    未实现本协议的 `LLMService` 走无工具降级路径。
    """

    async def chat_with_tools(
        self,
        messages: list[ProviderMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> LLMReply: ...
