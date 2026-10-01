"""LLM 端口（domain 持有的抽象，实现由 infrastructure 提供）。

- `LLMService`（Protocol）：统一的 `chat(messages, *, session_id)` 入口，返回文本；
  另含 `astream`，逐段产出内容增量（真 token 流，ADR-0005 §10）。
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

流式（#58 / #59 / ADR-0005 §10）：`astream` 只发出可见 `content` 增量；工具调用轮
（`tool_call_chunks`）不产生下游 token，其前置引导语视为临时文本，由最终持久
`character_speech` 覆盖。事件流只存最终完整文本。

工具调用与流式并存（#59）：`astream_with_tools` 是工具链路的流式入口，逐段产出
`StreamChunk`——可见 `content` 与**工具调用分片**分属两条通道。分片不是给玩家看的
文本，而是 LangChain agent 组装 `tool_calls` 的原料：丢了它工具节点永远不会触发
（ADR-0004）。「忽略 tool_call_chunks」指的是**不把它当可见文本下发**，不是不产出。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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


@dataclass(frozen=True)
class ToolCallDelta:
    """工具调用的单个流式分片（OpenAI streaming delta 的领域投影）。

    provider 把一个 tool_call 拆成多片下发：首片带 `id` 与函数名，后续片只带参数
    JSON 的片段。`index` 是同一轮内多个工具的排序位，拼装时按它归并。
    """

    index: int
    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass(frozen=True)
class StreamChunk:
    """流式往返的一段：可见 `content` 增量与工具调用分片（同段可并存）。

    `content` 是唯一向下游（WS/前端）可见的部分；`tool_calls` 供 agent 组装工具
    调用，`usage` 由 provider 在末段回报（多数 OpenAI-compatible provider 需要
    `stream_options.include_usage`，未开则为 None，计量回落到估算）。
    """

    content: str = ""
    tool_calls: tuple[ToolCallDelta, ...] = ()
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

    def astream(
        self,
        messages: list[Message],
        *,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> AsyncIterator[str]:
        """逐段产出可见 `content` 增量（async generator，无需 await 即调用）。

        这是端口的**必需成员**（实现应提供，见 `ChatLLMService`/`DeterministicAgentLLM`）；
        `UsageRecordingLLM` 为兼容既有 chat-only 实现，用 `getattr` 探测缺失并降级为
        单段产出。
        """
        ...


@runtime_checkable
class ToolCallingLLM(Protocol):
    """可选能力：支持工具调用的 LLM 实现（LangChain agent 的工具链路依赖）。

    工具 schema 采用 OpenAI 函数调用格式；返回 `LLMReply`（含 tool_calls）。
    未实现本协议的 `LLMService` 走无工具降级路径。流式入口 `astream_with_tools`
    同属可选能力，缺失时退回非流式单轮。
    """

    async def chat_with_tools(
        self,
        messages: list[ProviderMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> LLMReply: ...

    def astream_with_tools(
        self,
        messages: list[ProviderMessage],
        *,
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> AsyncIterator[StreamChunk]:
        """`chat_with_tools` 的流式版本：逐段产出 `StreamChunk`（#59）。

        与 `chat_with_tools` 一样是**可选能力**：未实现时 `WenjingChatModel._astream`
        回落到非流式单轮（ADR-0005 §10 允许的「工具轮非流式」降级）。
        """
        ...
