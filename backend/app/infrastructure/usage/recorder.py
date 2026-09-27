"""LLM 用量计量接缝（issue #22 / ADR-0002 §5）。

设计要点：
- **深模块**：`UsageRecordingLLM` 暴露与 `LLMService` 相同的 `chat`（以及可选的
  `chat_with_tools`），内部完成 token 估算 + 落库；调用方（Agent / Stage1）无需感知
  计量细节。工具调用 Agent 一轮内多次往返时，每次往返单独计一条。
- **best-effort**：计量失败绝不影响主流程——`UsageRecorder.record` 吞掉异常并告警。
- **无状态**：`UsageRecordingLLM` 由调用方按上下文（org/user/script/session）构造，
  不依赖全局可变状态，天然适配并发协程。

token 计数说明：底层 provider 未统一回传 usage 时，用 `estimate_tokens` 估算
（CJK 约 1.5 字/token）；接入可回传 usage 的 provider 时替换 `token_counter` 即可。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.enums import UsagePurpose
from app.domain.llm import LLMReply, TokenUsage
from app.infrastructure.models.llm_usage import LlmUsage

logger = logging.getLogger("wenjing.usage.recorder")


def estimate_tokens(text: str) -> int:
    """粗略 token 估算（约 2 字符/token；provider 未回传 usage 时的兜底）。"""
    return max(1, (len(text) + 1) // 2)


@dataclass(frozen=True)
class UsageContext:
    """一次 LLM 调用的归属上下文（谁是调用方、属于哪个剧本/会话）。"""

    org_id: uuid.UUID
    user_id: uuid.UUID
    script_id: int | None = None
    session_id: uuid.UUID | None = None


class UsageRecorder:
    """把调用明细写入 `llm_usage` 的薄适配器（best-effort，独立事务）。"""

    def __init__(self, *, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = session_factory

    def wrap(self, llm: Any, context: UsageContext) -> UsageRecordingLLM:
        """用本记录器与给定归属上下文包装一个 LLM（供组合根/应用层复用）。"""
        return UsageRecordingLLM(llm, recorder=self, context=context)

    async def record(
        self,
        context: UsageContext,
        *,
        provider: str,
        model: str,
        purpose: UsagePurpose,
        messages: Sequence[dict[str, str]],
        completion: str,
        usage: TokenUsage | None = None,
    ) -> None:
        """写入一条计量记录；任何失败只告警，不向调用方抛出。

        优先采信 provider 回报的真实 `usage`；缺失时按文本估算。
        """
        if usage is not None:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            total_tokens = usage.total_tokens
        else:
            prompt_tokens = sum(estimate_tokens(m.get("content", "")) for m in messages)
            completion_tokens = estimate_tokens(completion)
            total_tokens = prompt_tokens + completion_tokens
        try:
            async with self._factory() as s:
                s.add(
                    LlmUsage(
                        provider=provider or "unknown",
                        model=model or "unknown",
                        purpose=purpose.value,
                        prompt_tokens=prompt_tokens,
                        completion_tokens=completion_tokens,
                        total_tokens=total_tokens,
                        org_id=context.org_id,
                        user_id=context.user_id,
                        script_id=context.script_id,
                        session_id=context.session_id,
                    )
                )
                await s.commit()
        except Exception as exc:  # noqa: BLE001 - 计量永不阻断业务
            logger.warning(
                "llm_usage_record_failed error=%s purpose=%s org=%s",
                exc,
                purpose.value,
                context.org_id,
            )


class UsageRecordingLLM:
    """`LLMService` 装饰器：委托内层调用，成功后台账一条 `llm_usage`。"""

    def __init__(
        self,
        inner: Any,
        *,
        recorder: UsageRecorder,
        context: UsageContext,
    ) -> None:
        self._inner = inner
        self._recorder = recorder
        self._context = context
        self.provider = getattr(inner, "provider", "") or "unknown"
        self.model = getattr(inner, "model", "") or "unknown"

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> str:
        usage: TokenUsage | None = None
        chat_with_usage = getattr(self._inner, "chat_with_usage", None)
        if chat_with_usage is not None:
            completion, usage = await chat_with_usage(
                messages, session_id=session_id, purpose=purpose
            )
        else:
            completion = await self._inner.chat(
                messages, session_id=session_id, purpose=purpose
            )
        await self._recorder.record(
            self._context,
            provider=self.provider,
            model=self.model,
            purpose=purpose,
            messages=messages,
            completion=completion,
            usage=usage,
        )
        return completion

    async def chat_with_tools(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> LLMReply:
        """工具调用链路的计量委托：每次往返（工具选择 / 最终答复）单独计一条。"""
        chat_with_tools = getattr(self._inner, "chat_with_tools", None)
        if chat_with_tools is None:
            # 内层不支持工具调用：降级为无工具单轮，仍计量。
            completion = await self.chat(
                _plain_messages(messages), session_id=session_id, purpose=purpose
            )
            return LLMReply(content=completion)
        reply = await chat_with_tools(
            messages, tools=tools, session_id=session_id, purpose=purpose
        )
        # 工具选择轮 completion 为空是正常的；只有 provider 未回报 usage 时才会用
        # 文本估算，写工具名进去会污染 completion token 语义，故只记 content。
        await self._recorder.record(
            self._context,
            provider=self.provider,
            model=self.model,
            purpose=purpose,
            messages=_plain_messages(messages),
            completion=reply.content,
            usage=reply.usage,
        )
        return reply

    async def astream(
        self,
        messages: list[dict[str, str]],
        *,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> AsyncIterator[str]:
        """流式委托 + 计量：一次往返记一条（#58 / ADR-0005 §10）。

        内层未实现 `astream` 时降级为非流式 `chat`，单段产出并计量（行为无回归）。
        正常结束时按累计文本计量；若在产出任何内容前失败/被中断，则不写记录，
        避免为失败的调用留下 completion_tokens=1 的幻影账（与非流式 chat 一致）。
        """
        astream = getattr(self._inner, "astream", None)
        if astream is None:
            text = await self.chat(messages, session_id=session_id, purpose=purpose)
            yield text
            return
        parts: list[str] = []
        completed = False
        try:
            async for delta in astream(messages, session_id=session_id, purpose=purpose):
                parts.append(delta)
                yield delta
            completed = True
        finally:
            if parts or completed:
                await self._recorder.record(
                    self._context,
                    provider=self.provider,
                    model=self.model,
                    purpose=purpose,
                    messages=messages,
                    completion="".join(parts),
                    usage=None,
                )


def _plain_messages(messages: Sequence[dict]) -> list[dict[str, str]]:
    """把工具链路消息规整为计量用的 role/content 文本对（token 估算不关心 tool_calls）。"""
    out: list[dict[str, str]] = []
    for m in messages:
        content = m.get("content", "")
        if not isinstance(content, str):
            content = "" if content is None else str(content)
        out.append({"role": str(m.get("role", "user")), "content": content})
    return out


__all__ = [
    "UsageContext",
    "UsageRecorder",
    "UsageRecordingLLM",
    "estimate_tokens",
]
