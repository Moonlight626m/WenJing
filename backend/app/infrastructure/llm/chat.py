"""基于 OpenAI-compatible chat completions 的 LLM 生产实现（infrastructure 适配器）。

通过 `base_url` + `model` 即可对接任意 OpenAI-compatible provider
（OpenAI / DeepSeek / Qwen…）；显式 `provider` 仅用于日志与语义标记。
实现 domain/llm.LLMService 端口；推荐经 `ModelConfig` / `ModelServiceFactory` 构造。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.llm import LLMReply, Message, TokenUsage, ToolCall
from app.infrastructure.errx import codes, wrap

logger = logging.getLogger("wenjing.agents.llm")


class ChatLLMService:
    """domain/llm.LLMService 的 OpenAI-compatible 生产实现。"""

    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str | None = None,
        provider: str = "openai",
        temperature: float = 0.7,
        max_tokens: int | None = None,
        max_concurrency: int = 5,
        timeout_seconds: int = 30,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout_seconds

    def _provider_headers(self, session_id: str) -> dict[str, str] | None:
        """opencodego 要求每个会话带稳定 `x-opencode-session` 头（路由/缓存优化），
        且客户端用自有 UA 标识（OpenCode Go 官方要求，泛 SDK 名会被视为可疑流量）。"""
        if self.provider != "opencodego":
            return None
        return {
            "User-Agent": "wenjing/0.1",
            "x-opencode-session": session_id or "wenjing-anonymous",
        }

    async def chat(
        self,
        messages: list[Message],
        *,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> str:
        content, _usage = await self.chat_with_usage(
            messages, session_id=session_id, purpose=purpose
        )
        return content

    async def chat_with_usage(
        self,
        messages: list[Message],
        *,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> tuple[str, TokenUsage | None]:
        """同 `chat`，额外返回 provider 回报的真实 token 用量（#22 计量采信）。"""
        content, _calls, usage = await self._invoke(
            messages, session_id=session_id, purpose=purpose
        )
        return content, usage

    async def chat_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> LLMReply:
        """带 OpenAI 工具 schema 的对话；返回文本 + tool_calls + 用量。"""
        content, calls, usage = await self._invoke(
            messages, session_id=session_id, purpose=purpose, tools=tools
        )
        return LLMReply(content=content, tool_calls=calls, usage=usage)

    async def _invoke(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str,
        purpose: UsagePurpose,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, tuple[ToolCall, ...], TokenUsage | None]:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=self._provider_headers(session_id),
        )
        async with self._semaphore:
            logger.info(
                "llm_call_start",
                extra={
                    "session_id": session_id or None,
                    "wj_extra": {
                        "provider": self.provider,
                        "model": self.model,
                        "messages": len(messages),
                        "tools": len(tools) if tools else 0,
                        "purpose": purpose.value,
                    },
                },
            )
            try:
                req: dict[str, Any] = {
                    "model": self.model,
                    "messages": messages,
                    "temperature": self._temperature,
                }
                if self._max_tokens is not None:
                    req["max_tokens"] = self._max_tokens
                if tools:
                    req["tools"] = tools
                resp = await asyncio.wait_for(
                    client.chat.completions.create(**req),
                    timeout=self._timeout,
                )
                message = resp.choices[0].message
                content = message.content or ""
                calls = _tool_calls(message)
                usage = _token_usage(resp)
                logger.info(
                    "llm_call_end",
                    extra={
                        "session_id": session_id or None,
                        "wj_extra": {
                            "provider": self.provider,
                            "model": self.model,
                            "purpose": purpose.value,
                            "content": content,  # 模型响应全文（业务层关键信息）
                            "tool_calls": [c.name for c in calls],
                            "prompt_tokens": usage.prompt_tokens if usage else None,
                            "completion_tokens": usage.completion_tokens if usage else None,
                        },
                    },
                )
            except Exception as exc:
                logger.error(
                    "llm_call_failed",
                    extra={
                        "wj_extra": {"reason": str(exc)},
                        "session_id": session_id or None,
                    },
                )
                raise wrap(exc, codes.LLM_CALL_FAILED, extra={"reason": str(exc)}) from exc
            finally:
                await client.close()
            return content, calls, usage


def _tool_calls(message: Any) -> tuple[ToolCall, ...]:
    """解析 OpenAI 响应中的 tool_calls；参数为 JSON 字符串，解析失败按空参处理。"""
    raw = getattr(message, "tool_calls", None) or []
    calls: list[ToolCall] = []
    for item in raw:
        fn = getattr(item, "function", None)
        name = getattr(fn, "name", None)
        if not name:
            continue
        try:
            arguments = json.loads(fn.arguments or "{}")
        except (TypeError, ValueError):
            arguments = {}
        if not isinstance(arguments, dict):
            arguments = {"value": arguments}
        calls.append(
            ToolCall(id=str(getattr(item, "id", "") or ""), name=name, arguments=arguments)
        )
    return tuple(calls)


def _token_usage(resp: Any) -> TokenUsage | None:
    """从 provider 响应中读取真实 token 用量；字段缺失时为 None（回落估算）。"""
    raw = getattr(resp, "usage", None)
    if raw is None:
        return None
    prompt = getattr(raw, "prompt_tokens", None)
    completion = getattr(raw, "completion_tokens", None)
    if prompt is None or completion is None:
        return None
    total = getattr(raw, "total_tokens", None)
    return TokenUsage(
        prompt_tokens=int(prompt),
        completion_tokens=int(completion),
        total_tokens=int(total) if total is not None else int(prompt) + int(completion),
    )
