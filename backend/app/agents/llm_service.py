"""LLM Service 抽象与生产实现。

- `LLMService`（Protocol）：统一的 `chat(messages, *, session_id)` 入口，返回文本。
- MVP 阶段不接真实 provider，仅定义接口与默认实现；测试注入 `FakeLLMService`。
- 生产实现预留 provider 配置切换（OpenAI/DeepSeek/Qwen 等，D7）。

设计约束（design_00 D7）：单例会所，每轮每 Agent 一次 LLM 调用；
错误统一包装为 `codes.LLM_CALL_FAILED`。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol, TypeAlias, runtime_checkable

from app.errx import codes, wrap

logger = logging.getLogger("wenjing.agents.llm")

Message: TypeAlias = dict[str, str]  # {"role": ..., "content": ...}


@runtime_checkable
class LLMService(Protocol):
    """可注入的 LLM 服务接口。"""

    async def chat(
        self,
        messages: list[Message],
        *,
        session_id: str = "",
    ) -> str: ...


class ChatLLMService:
    """基于 OpenAI-compatible chat completions 的生产实现（预留，MVP 不启用）。

    通过 `base_url` + `model` 即可对接任意 OpenAI-compatible provider
    （OpenAI / DeepSeek / Qwen…）；显式 `provider` 仅用于日志与语义标记。
    推荐经 `ModelConfig` / `ModelServiceFactory` 构造。
    """

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

    async def chat(self, messages: list[Message], *, session_id: str = "") -> str:
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        async with self._semaphore:
            logger.info(
                "llm_call_start",
                extra={
                    "provider": self.provider,
                    "model": self.model,
                    "messages": len(messages),
                    "session_id": session_id or None,
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
                resp = await asyncio.wait_for(
                    client.chat.completions.create(**req),
                    timeout=self._timeout,
                )
                content = resp.choices[0].message.content or ""
            except Exception as exc:
                logger.error(
                    "llm_call_failed",
                    extra={"reason": str(exc), "session_id": session_id or None},
                )
                raise wrap(exc, codes.LLM_CALL_FAILED, extra={"reason": str(exc)}) from exc
            finally:
                await client.close()
            return content
