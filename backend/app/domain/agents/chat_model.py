"""LangChain ChatModel 适配器：把 domain 的 `LLMService` 端口暴露为 `BaseChatModel`。

设计动机（ADR-0004，延续 docs/research/langgraph-workflow-study.md §3.5）：
- LangChain agent（`create_agent`）只认识标准 `BaseChatModel`，而本项目所有 LLM
  调用都要经过 `LLMService` 端口以保留用量计量 / purpose 分类 / 超时与错误码。
- 本适配器是那层薄桥：`_agenerate` 把 LangChain 消息转成 provider 消息，调用
  `chat_with_tools`（若实现）或降级 `chat_with_usage`/`chat`，再把结果转回
  `AIMessage`（含 tool_calls 与 usage_metadata）。
- 仅实现 `_agenerate`（全链路 async）；同步 `_generate` 不支持。
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

from langchain_core.callbacks import AsyncCallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

from app.contracts.enums import UsagePurpose
from app.domain.llm import TokenUsage

_ROLE_BY_TYPE = {
    "system": "system",
    "human": "user",
    "ai": "assistant",
    "tool": "tool",
}


class WenjingChatModel(BaseChatModel):
    """把 `LLMService`（经计量装饰）适配为 LangChain `BaseChatModel`。"""

    service: Any
    purpose: UsagePurpose = UsagePurpose.AGENT
    session_id: str = ""
    bound_tools: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "wenjing-chat"

    def bind_tools(
        self,
        tools: Sequence[dict[str, Any] | type | Any],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ) -> WenjingChatModel:
        """记录 OpenAI 工具 schema 并返回**新实例**（不修改自身）。

        LangChain 的 default `bind_tools` 未实现时会直接抛错，故显式转为
        OpenAI 函数调用格式后绑定；遵守 `bind_*` 返回新 Runnable 的契约，避免
        共享模型上的可变状态。`tool_choice`/其他参数当前不下发（模型不产出
        结构化输出，工具选择交由 provider 默认行为）。
        """
        formatted = [
            t if isinstance(t, dict) else convert_to_openai_tool(t) for t in tools
        ]
        return self.model_copy(update={"bound_tools": formatted})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:  # pragma: no cover - 后端全 async
        raise NotImplementedError("WenjingChatModel 只支持异步路径")

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        dict_messages = [_to_provider_message(m) for m in messages]
        tools = kwargs.get("tools") or self.bound_tools
        service = self.service

        if tools and hasattr(service, "chat_with_tools"):
            reply = await service.chat_with_tools(
                dict_messages,
                tools=tools,
                session_id=self.session_id,
                purpose=self.purpose,
            )
            message = AIMessage(
                content=reply.content,
                tool_calls=[
                    {
                        "name": call.name,
                        "args": call.arguments,
                        "id": call.id,
                        "type": "tool_call",
                    }
                    for call in reply.tool_calls
                ],
                usage_metadata=_usage_metadata(reply.usage),
            )
        else:
            content, usage = await _complete(service, dict_messages, self)
            message = AIMessage(content=content, usage_metadata=_usage_metadata(usage))

        return ChatResult(generations=[ChatGeneration(message=message)])


async def _complete(
    service: Any, messages: Sequence[dict[str, Any]], model: WenjingChatModel
) -> tuple[str, TokenUsage | None]:
    """无工具路径：优先采信 provider 真实用量，否则回落到纯文本 `chat`。"""
    chat_with_usage = getattr(service, "chat_with_usage", None)
    if chat_with_usage is not None:
        return await chat_with_usage(
            messages, session_id=model.session_id, purpose=model.purpose
        )
    content = await service.chat(
        messages, session_id=model.session_id, purpose=model.purpose
    )
    return content, None


def _to_provider_message(message: BaseMessage) -> dict[str, Any]:
    """LangChain 消息 → OpenAI-compatible 消息（保留 tool_calls / tool_call_id）。"""
    role = _ROLE_BY_TYPE.get(message.type, "user")
    content = message.content
    if not isinstance(content, str):
        content = "" if content is None else str(content)

    if message.type == "ai":
        calls = getattr(message, "tool_calls", None) or []
        if calls:
            return {
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": call.get("id", ""),
                        "type": "function",
                        "function": {
                            "name": call.get("name", ""),
                            "arguments": json.dumps(
                                call.get("args", {}) or {}, ensure_ascii=False
                            ),
                        },
                    }
                    for call in calls
                ],
            }
        return {"role": "assistant", "content": content}

    if message.type == "tool":
        return {
            "role": "tool",
            "content": content,
            "tool_call_id": getattr(message, "tool_call_id", ""),
        }

    return {"role": role, "content": content}


def _usage_metadata(usage: TokenUsage | None) -> dict[str, int] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.prompt_tokens,
        "output_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


__all__ = ["WenjingChatModel"]
