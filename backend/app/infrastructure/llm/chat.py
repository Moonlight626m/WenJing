"""基于 OpenAI-compatible chat completions 的 LLM 生产实现（infrastructure 适配器）。

通过 `base_url` + `model` 即可对接任意 OpenAI-compatible provider
（OpenAI / DeepSeek / Qwen…）；显式 `provider` 仅用于日志与语义标记。
实现 domain/llm.LLMService 端口；推荐经 `ModelConfig` / `ModelServiceFactory` 构造。
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.llm import Message, TokenUsage
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
        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
        async with self._semaphore:
            logger.info(
                "llm_call_start",
                extra={
                    "session_id": session_id or None,
                    "wj_extra": {
                        "provider": self.provider,
                        "model": self.model,
                        "messages": len(messages),
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
                resp = await asyncio.wait_for(
                    client.chat.completions.create(**req),
                    timeout=self._timeout,
                )
                content = resp.choices[0].message.content or ""
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
            return content, usage


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
