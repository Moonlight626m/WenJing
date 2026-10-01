"""基于 OpenAI-compatible chat completions 的 LLM 生产实现（infrastructure 适配器）。

通过 `base_url` + `model` 即可对接任意 OpenAI-compatible provider
（OpenAI / DeepSeek / Qwen…）；显式 `provider` 仅用于日志与语义标记。
实现 domain/llm.LLMService 端口；推荐经 `ModelConfig` / `ModelServiceFactory` 构造。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.llm import (
    LLMReply,
    Message,
    StreamChunk,
    TokenUsage,
    ToolCall,
    ToolCallDelta,
)
from app.infrastructure.errx import Error, codes, exc_reason, wrap

logger = logging.getLogger("wenjing.agents.llm")

#: 流式相邻 chunk 的空闲上限（秒），与「整次调用上界」分开（#65）。
#: `_timeout` 定的是**整次** non-streaming 调用的预算，要覆盖长 JSON 的整段生成；
#: 拿同一个数当流式空闲间隔太宽松——学生端会对着不动的字幕干等好几分钟。
#: 也不宜收得过紧：推理型模型思考期间本就不产 chunk。
STREAM_IDLE_TIMEOUT_CAP = 150.0


def is_timeout(exc: BaseException) -> bool:
    """该异常是否为一次超时（#65）。

    `asyncio.wait_for` 抛的是内建 `TimeoutError`（3.11 起 `asyncio.TimeoutError` 是它
    的别名）；provider SDK 自带的超时类（`openai.APITimeoutError`、`httpx.ReadTimeout`）
    **不是**它的子类，只能按类名识别——这是跨 SDK 版本唯一稳定的判据，认不出就当普通
    失败处理（宁可归错到 `LLM_CALL_FAILED`，也不要让重试逻辑吃掉真正的 provider 报错）。
    """
    if isinstance(exc, TimeoutError):
        return True
    return "timeout" in type(exc).__name__.lower()


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
        timeout_seconds: float = 30,
        timeout_retries: int = 1,
        retry_backoff_seconds: float = 2.0,
    ) -> None:
        self.provider = provider
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout_seconds
        # 流式空闲判定用这个上界（见 `STREAM_IDLE_TIMEOUT_CAP`）：调大 `_timeout`
        # 不会顺带把流式静默也拉长。
        self._stream_timeout = min(timeout_seconds, STREAM_IDLE_TIMEOUT_CAP)
        self._timeout_retries = max(0, timeout_retries)
        self._retry_backoff = max(0.0, retry_backoff_seconds)

    # ===== 失败分类与重试（#65）=====

    def _may_retry(self, exc: BaseException, attempt: int) -> bool:
        """是否该再试一次：只重试超时，且未超出重试预算。

        provider 的 4xx（参数错、额度耗尽、模型不存在）再试一次只是白等一次，真正
        "再试一次可能就好"的形态只有超时。`attempt` 是**已完成**的尝试次数（0 起）。
        """
        return attempt < self._timeout_retries and is_timeout(exc)

    async def _wait_before_retry(
        self, event: str, exc: BaseException, attempt: int, session_id: str
    ) -> None:
        """记一次重试日志并指数退避。`attempt` 是**已完成**的尝试次数（0 起）。"""
        delay = self._retry_backoff * (2**attempt)
        logger.warning(
            event,
            extra={
                "session_id": session_id or None,
                "retry_count": attempt + 1,
                "wj_extra": {
                    "reason": exc_reason(exc),
                    "delay_seconds": f"{delay:g}",
                },
            },
        )
        await asyncio.sleep(delay)

    @staticmethod
    def _code_for(exc: BaseException) -> int:
        """失败分类：#65 要求超时与 provider 报错分列两个码。"""
        return codes.LLM_TIMEOUT if is_timeout(exc) else codes.LLM_CALL_FAILED

    def _failure(self, exc: BaseException, *, timeout: float, **extra: Any) -> Error:
        """把底层异常包装成对外错误。

        `reason` 一律用 `exc_reason`（`类型: 消息`）——`str(TimeoutError())` 是空串，
        正是原先把现场丢干净的原因。`timeout` 是该次调用**实际生效**的上界（流式与
        非流式不同）。
        """
        payload: dict[str, str] = {"reason": exc_reason(exc)}
        if is_timeout(exc):
            payload["timeout"] = f"{timeout:g}"
        return wrap(exc, self._code_for(exc), extra={**payload, **extra})

    def _log_failure(
        self,
        event: str,
        exc: BaseException,
        attempt: int,
        session_id: str,
        **context: Any,
    ) -> None:
        """终局失败日志：带上异常类型、错误码与已试次数（#65 的现场可诊断性）。

        `context` 给各调用点补自己的现场（流式失败要带已经吐了几段）。
        """
        logger.error(
            event,
            extra={
                "session_id": session_id or None,
                "retry_count": attempt,
                "wj_extra": {
                    "reason": exc_reason(exc),
                    "error_code": self._code_for(exc),
                    **context,
                },
            },
        )

    def _provider_headers(self, session_id: str) -> dict[str, str] | None:
        """opencodego 要求每个会话带稳定 `x-opencode-session` 头（路由/缓存优化），
        且客户端用自有 UA 标识（OpenCode Go 官方要求，泛 SDK 名会被视为可疑流量）。"""
        if self.provider != "opencodego":
            return None
        return {
            "User-Agent": "wenjing/0.1",
            "x-opencode-session": session_id or "wenjing-anonymous",
        }

    @contextlib.asynccontextmanager
    async def _client(self, session_id: str) -> AsyncIterator[Any]:
        """每请求一个 OpenAI 客户端（provider 头随会话），退出时确保关闭。"""
        from openai import AsyncOpenAI

        client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            default_headers=self._provider_headers(session_id),
        )
        try:
            yield client
        finally:
            await client.close()

    def _request(
        self,
        messages: list[dict[str, Any]],
        *,
        stream: bool = False,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """构造 OpenAI-compatible 请求体（流式/工具共用）。"""
        req: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": self._temperature,
        }
        if self._max_tokens is not None:
            req["max_tokens"] = self._max_tokens
        if stream:
            req["stream"] = True
        if tools:
            req["tools"] = tools
        return req

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

    async def astream(
        self,
        messages: list[Message],
        *,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> AsyncIterator[str]:
        """无工具流式：逐段 yield 可见 `content` 增量（#58 / ADR-0005 §10）。

        复用 `astream_with_tools` 的同一套取流/超时/错误处理，只把可见通道剖出来。
        """
        async for chunk in self.astream_with_tools(
            messages, tools=None, session_id=session_id, purpose=purpose
        ):
            if chunk.content:
                yield chunk.content

    async def astream_with_tools(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> AsyncIterator[StreamChunk]:
        """带工具 schema 的流式往返（#59 / ADR-0005 §10）。

        逐段产出 `StreamChunk`：`content` 是可见文本，`tool_calls` 是工具调用分片。
        两者走**不同通道**——分片交给 LangChain 拼装 tool_calls，绝不作为可见文本
        下发；工具轮的引导语是**临时文本**，由最终持久 `character_speech` 覆盖。

        超时按**相邻 chunk 的空闲间隔**计（不把消费者处理/背压时间算作 provider
        超时）；超时抛 `LLM_TIMEOUT`、其余失败抛 `LLM_CALL_FAILED`（#65）。

        重试（#65）：只在**一段 chunk 都还没交给消费者**时重试。已经 yield 出去的
        分片收不回来——重开一条流会让消费端把同一段工具参数累加两遍（可见文本更糟，
        学生眼前会重念一遍）。空闲超时发生在首片之前才是安全的，而这也正是最常见的
        形态（provider 卡在起手）。
        """
        chunks = 0
        emitted = False
        attempt = 0
        async with self._client(session_id) as client, self._semaphore:
            logger.info(
                "llm_stream_start",
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
            while True:
                try:
                    stream = await asyncio.wait_for(
                        client.chat.completions.create(
                            **self._request(messages, stream=True, tools=tools)
                        ),
                        timeout=self._stream_timeout,
                    )
                    iterator = stream.__aiter__()
                    while True:
                        try:
                            raw = await asyncio.wait_for(
                                iterator.__anext__(), timeout=self._stream_timeout
                            )
                        except StopAsyncIteration:
                            break
                        text = _delta_content(raw)
                        calls = _delta_tool_calls(raw)
                        usage = _token_usage(raw)
                        if not text and not calls and usage is None:
                            continue
                        if text:
                            chunks += 1
                        emitted = True
                        yield StreamChunk(content=text, tool_calls=calls, usage=usage)
                except Exception as exc:
                    if not emitted and self._may_retry(exc, attempt):
                        await self._wait_before_retry(
                            "llm_stream_retry", exc, attempt, session_id
                        )
                        attempt += 1
                        continue
                    self._log_failure(
                        "llm_stream_failed", exc, attempt, session_id, chunks=chunks
                    )
                    raise self._failure(
                        exc,
                        timeout=self._stream_timeout,
                        retry_count=attempt,
                        chunks=chunks,
                    ) from exc
                break
            logger.info(
                "llm_stream_end",
                extra={
                    "session_id": session_id or None,
                    "wj_extra": {
                        "provider": self.provider,
                        "model": self.model,
                        "purpose": purpose.value,
                        "chunks": chunks,
                        "retry_count": attempt,
                    },
                },
            )

    async def _invoke(
        self,
        messages: list[dict[str, Any]],
        *,
        session_id: str,
        purpose: UsagePurpose,
        tools: list[dict[str, Any]] | None = None,
    ) -> tuple[str, tuple[ToolCall, ...], TokenUsage | None]:
        async with self._client(session_id) as client, self._semaphore:
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
            attempt = 0
            while True:
                try:
                    resp = await asyncio.wait_for(
                        client.chat.completions.create(
                            **self._request(messages, tools=tools)
                        ),
                        timeout=self._timeout,
                    )
                    message = resp.choices[0].message
                    content = message.content or ""
                    calls = _tool_calls(message)
                    usage = _token_usage(resp)
                except Exception as exc:
                    # 非流式调用是整次幂等的，重试不会产生重复输出（#65）。
                    if self._may_retry(exc, attempt):
                        await self._wait_before_retry(
                            "llm_call_retry", exc, attempt, session_id
                        )
                        attempt += 1
                        continue
                    self._log_failure("llm_call_failed", exc, attempt, session_id)
                    raise self._failure(
                        exc, timeout=self._timeout, retry_count=attempt
                    ) from exc
                break
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
                        "retry_count": attempt,
                    },
                },
            )
            return content, calls, usage


def _delta_content(chunk: Any) -> str:
    """从流式 chunk 中取出可见 content 增量；工具轮/结束块无 content 时返回空串。"""

    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ""
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return ""
    return getattr(delta, "content", None) or ""


def _delta_tool_calls(chunk: Any) -> tuple[ToolCallDelta, ...]:
    """从流式 chunk 中取出工具调用分片；无分片（普通文本段）时返回空元组。

    分片参数是**未完成的 JSON 片段**，只做透传，不在此处解析——拼装由 LangChain
    的 `AIMessageChunk` 归并完成（按 `index` 归并、`arguments` 累加）。
    """
    choices = getattr(chunk, "choices", None) or []
    if not choices:
        return ()
    delta = getattr(choices[0], "delta", None)
    if delta is None:
        return ()
    raw = getattr(delta, "tool_calls", None) or []
    out: list[ToolCallDelta] = []
    for index, item in enumerate(raw):
        fn = getattr(item, "function", None)
        out.append(
            ToolCallDelta(
                index=int(getattr(item, "index", index) or 0),
                id=str(getattr(item, "id", "") or ""),
                name=str(getattr(fn, "name", "") or ""),
                arguments=str(getattr(fn, "arguments", "") or ""),
            )
        )
    return tuple(out)


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
