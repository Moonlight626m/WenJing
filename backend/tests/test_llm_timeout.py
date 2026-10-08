"""LLM 超时的可观测性与重试（issue #65）。

无网络、无 DB：用 scripted 的 `completions.create` 桩驱动 `ChatLLMService`。
超时态多数直接抛 `TimeoutError`（`asyncio.wait_for` 掐断时抛的就是它），另有一条
用例走真实 `wait_for` 以验证接线；退避用 monkeypatch 掉 `asyncio.sleep` 来观察，
不真的等。
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from app.contracts.enums import UsagePurpose
from app.domain.agents.character import CharacterAgent
from app.domain.game.types import CharacterSetting, PlayerAction
from app.domain.llm import StreamChunk
from app.infrastructure.diagnostics.errors import envelope_for, safe_message
from app.infrastructure.errx import Error, codes, new
from app.infrastructure.llm.chat import (
    STREAM_IDLE_TIMEOUT_CAP,
    ChatLLMService,
    is_timeout,
)
from tests.test_agent_tools import _FakeWorld


class APITimeoutError(Exception):
    """形如 provider SDK 的超时类：名字像，但**不**继承内建 `TimeoutError`。"""


class _QuietError(Exception):
    """消息为空的异常——`str(TimeoutError()) == ''` 是 #65 里 reason 丢空的成因。"""


# ===== 桩：chat.completions.create =====


class _Delta:
    def __init__(self, content: str, tool_calls: list | None = None) -> None:
        self.content = content
        self.tool_calls = tool_calls


class _Chunk:
    def __init__(self, content: str) -> None:
        self.choices = [type("C", (), {"delta": _Delta(content)})()]


class _Function:
    def __init__(self, name: str, arguments: str) -> None:
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, index: int, call_id: str, name: str, arguments: str) -> None:
        self.index = index
        self.id = call_id
        self.function = _Function(name, arguments)


def _tool_chunk() -> _Chunk:
    """只有工具分片、没有可见文本的 chunk（`chunks` 不涨，但对端已经收到东西了）。"""
    call = _ToolCall(0, "c1", "view_world_progress", '{"k":')
    chunk = _Chunk("")
    chunk.choices[0].delta.tool_calls = [call]
    return chunk


class _Message:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls = None


class _Response:
    def __init__(self, content: str) -> None:
        self.choices = [type("C", (), {"message": _Message(content)})()]
        self.usage = None


class _Stream:
    """一次给一片、给完即停。"""

    def __init__(self, contents: list[str]) -> None:
        self._items = iter(contents)

    def __aiter__(self):  # noqa: ANN204
        return self

    async def __anext__(self):  # noqa: ANN204
        try:
            return _Chunk(next(self._items))
        except StopIteration:
            raise StopAsyncIteration from None


class _DyingStream:
    """先给一片再超时：验证「已经流出去的内容不重来」。"""

    def __init__(self, first: _Chunk) -> None:
        self._first = first
        self._sent = False

    def __aiter__(self):  # noqa: ANN204
        return self

    async def __anext__(self):  # noqa: ANN204
        if not self._sent:
            self._sent = True
            return self._first
        raise TimeoutError


class _ScriptedCompletions:
    """按脚本逐次回答 `create()`。

    每一步可以是 `"ok"`（正常返回）、`"timeout"`（抛 `TimeoutError`）、
    `"hang"`（真的睡住，交给 `wait_for` 掐）、`"partial"`（流一段可见文本后超时）、
    `"partial_tool"`（流一段工具分片后超时），或一个异常实例（原样抛出）。
    """

    def __init__(self, script: list[object], *, chunks: tuple[str, ...] = ("甲", "乙")) -> None:
        self._script = list(script)
        self._chunks = list(chunks)
        self.calls = 0

    async def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.calls += 1
        step = self._script.pop(0) if self._script else "ok"
        if isinstance(step, BaseException):
            raise step
        if kwargs.get("stream"):
            if step == "partial":
                return _DyingStream(_Chunk(self._chunks[0]))
            if step == "partial_tool":
                return _DyingStream(_tool_chunk())
            if step == "timeout":
                raise TimeoutError
            return _Stream(self._chunks)
        if step == "hang":
            await asyncio.sleep(30)
        if step == "timeout":
            raise TimeoutError
        return _Response("完整答复")


def _patch_client(monkeypatch, completions: _ScriptedCompletions) -> None:
    client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()

    @contextlib.asynccontextmanager
    async def fake_client(self, session_id):  # noqa: ANN001, ANN202
        yield client

    monkeypatch.setattr(ChatLLMService, "_client", fake_client)


def _service(**overrides) -> ChatLLMService:
    # 退避归零：用例只关心"重不重试"，不关心等多久（退避另有专门用例）。
    overrides.setdefault("retry_backoff_seconds", 0.0)
    return ChatLLMService(model="m", api_key="k", provider="openai", **overrides)


def _messages() -> list[dict[str, str]]:
    return [{"role": "user", "content": "x"}]


async def _collect(llm: ChatLLMService, *, stream: bool) -> list[str]:
    """`astream` 的可见通道只吐文本（`StreamChunk` 是 `astream_with_tools` 的形状）。"""
    if not stream:
        return [await llm.chat(_messages())]
    return [c async for c in llm.astream(_messages())]


def _patch_sleep(monkeypatch) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return slept


# ===== 1. 失败分类：超时与 provider 报错分列 =====


async def test_timeout_raises_llm_timeout_not_call_failed(monkeypatch):
    """超时走独立的 `LLM_TIMEOUT`，不再混进 `LLM_CALL_FAILED`（#65 的核心）。"""
    _patch_client(monkeypatch, _ScriptedCompletions(["timeout"]))
    with pytest.raises(Error) as excinfo:
        await _service(timeout_retries=0, timeout_seconds=240).chat(_messages())
    assert excinfo.value.code == codes.LLM_TIMEOUT
    assert excinfo.value.extra["timeout"] == "240"
    assert "TimeoutError" in excinfo.value.extra["reason"], "reason 必须带异常类型名"


async def test_timeout_reason_is_not_empty_in_server_message(monkeypatch):
    """回归 #65：`str(TimeoutError())` 为空，服务端消息因此只剩「llm call failed: 」。"""
    _patch_client(monkeypatch, _ScriptedCompletions(["timeout"]))
    with pytest.raises(Error) as excinfo:
        await _service(timeout_retries=0).chat(_messages())
    assert "TimeoutError" in excinfo.value.msg
    assert "timed out" in excinfo.value.msg
    assert excinfo.value.extra["reason"].strip() == "TimeoutError:"


async def test_provider_error_keeps_type_name_even_with_empty_message(monkeypatch):
    """provider 报错仍归 `LLM_CALL_FAILED`，但 `reason` 带上类型名，不再是空串。"""
    _patch_client(monkeypatch, _ScriptedCompletions([_QuietError()]))
    with pytest.raises(Error) as excinfo:
        await _service(timeout_retries=3).chat(_messages())
    assert excinfo.value.code == codes.LLM_CALL_FAILED
    assert excinfo.value.extra["reason"] == "_QuietError: "


async def test_real_wait_for_timeout_is_classified_as_timeout(monkeypatch):
    """真的被 `wait_for` 掐断也走 `LLM_TIMEOUT`（不只信任桩抛的异常）。"""
    _patch_client(monkeypatch, _ScriptedCompletions(["hang"]))
    with pytest.raises(Error) as excinfo:
        await _service(timeout_retries=0, timeout_seconds=0.05).chat(_messages())
    assert excinfo.value.code == codes.LLM_TIMEOUT
    assert excinfo.value.extra["timeout"] == "0.05"


def test_is_timeout_covers_sdk_timeout_classes():
    """SDK 的超时类不继承内建 `TimeoutError`，只能按类名认。"""
    assert is_timeout(TimeoutError())
    assert is_timeout(APITimeoutError())
    assert not is_timeout(_QuietError())


# ===== 2. 重试：只重试超时、次数有界、指数退避 =====


async def test_timeout_is_retried_then_succeeds(monkeypatch):
    """#65 的原始病灶：一次慢调用即整轮失败。有了重试就不必整轮重来。"""
    completions = _ScriptedCompletions(["timeout", "ok"])
    _patch_client(monkeypatch, completions)
    assert await _service(timeout_retries=1).chat(_messages()) == "完整答复"
    assert completions.calls == 2


async def test_timeout_retries_are_bounded(monkeypatch):
    completions = _ScriptedCompletions(["timeout"] * 5)
    _patch_client(monkeypatch, completions)
    with pytest.raises(Error) as excinfo:
        await _service(timeout_retries=1).chat(_messages())
    assert completions.calls == 2, "首次 + 1 次重试"
    assert excinfo.value.extra["retry_count"] == "1"


async def test_provider_error_is_never_retried(monkeypatch):
    """参数错/额度耗尽这类 4xx 再试一次只是白等一次。"""
    completions = _ScriptedCompletions([RuntimeError("boom")] * 5)
    _patch_client(monkeypatch, completions)
    with pytest.raises(Error) as excinfo:
        await _service(timeout_retries=3).chat(_messages())
    assert completions.calls == 1
    assert excinfo.value.code == codes.LLM_CALL_FAILED


async def test_retry_backoff_grows_exponentially(monkeypatch):
    completions = _ScriptedCompletions(["timeout"] * 5)
    _patch_client(monkeypatch, completions)
    slept = _patch_sleep(monkeypatch)
    with pytest.raises(Error):
        await _service(timeout_retries=2, retry_backoff_seconds=2.0).chat(_messages())
    assert slept == [2.0, 4.0]


async def test_zero_retries_disables_retry(monkeypatch):
    completions = _ScriptedCompletions(["timeout"] * 3)
    _patch_client(monkeypatch, completions)
    with pytest.raises(Error) as excinfo:
        await _service(timeout_retries=0).chat(_messages())
    assert completions.calls == 1
    assert excinfo.value.extra["retry_count"] == "0"


# ===== 3. 流式：只在还没交出任何一片时重试 =====


async def test_stream_timeout_before_first_chunk_is_retried(monkeypatch):
    completions = _ScriptedCompletions(["timeout", "ok"], chunks=("甲", "乙"))
    _patch_client(monkeypatch, completions)
    assert await _collect(_service(timeout_retries=1), stream=True) == ["甲", "乙"]
    assert completions.calls == 2


async def test_stream_timeout_after_first_chunk_is_not_retried(monkeypatch):
    """已经 yield 出去的台词收不回来：重开一条流会让学生看到重念一遍。"""
    completions = _ScriptedCompletions(["partial", "ok"], chunks=("甲",))
    _patch_client(monkeypatch, completions)

    seen: list[str] = []
    with pytest.raises(Error) as excinfo:
        async for text in _service(timeout_retries=2).astream(_messages()):
            seen.append(text)

    assert seen == ["甲"], "不得重来"
    assert completions.calls == 1
    assert excinfo.value.code == codes.LLM_TIMEOUT
    assert "TimeoutError" in excinfo.value.extra["reason"]


async def test_stream_retry_is_blocked_once_a_tool_fragment_was_emitted(monkeypatch):
    """工具分片也算「已交出」。

    只看可见文本段数（`chunks`）会漏判：工具分片的 content 是空的，`chunks` 仍为 0，
    于是重开一条流，消费端把同一段参数累加两遍，工具调用直接坏掉。
    """
    completions = _ScriptedCompletions(["partial_tool", "ok"])
    _patch_client(monkeypatch, completions)

    seen: list[StreamChunk] = []
    with pytest.raises(Error) as excinfo:
        async for chunk in _service(timeout_retries=2).astream_with_tools(_messages()):
            seen.append(chunk)

    assert completions.calls == 1, "已经交出分片就不该重来"
    assert sum(len(c.tool_calls) for c in seen) == 1, "分片不得重复下发"
    assert excinfo.value.code == codes.LLM_TIMEOUT


async def test_stream_idle_deadline_is_capped_below_the_whole_call_budget(monkeypatch):
    """整次调用预算放宽后，流式空闲不该跟着一起变长（否则字幕干等几分钟）。"""
    _patch_client(monkeypatch, _ScriptedCompletions(["timeout"]))
    with pytest.raises(Error) as excinfo:
        async for _chunk in _service(
            timeout_retries=0, timeout_seconds=600
        ).astream_with_tools(_messages()):
            pass
    assert excinfo.value.extra["timeout"] == f"{STREAM_IDLE_TIMEOUT_CAP:g}"

    # 而非流式仍按整次预算（600）报数——两条路径的上界确实是分开的。
    _patch_client(monkeypatch, _ScriptedCompletions(["timeout"]))
    with pytest.raises(Error) as plain:
        await _service(timeout_retries=0, timeout_seconds=600).chat(_messages())
    assert plain.value.extra["timeout"] == "600"


# ===== 4. 五处登记 + 领域层不把码抹平 =====


def test_llm_timeout_is_registered_at_every_site():
    """漏登记只静默降级：这里把服务端消息模板、对外信封、用户可见消息三处一起钉住。"""
    exc = new(codes.LLM_TIMEOUT, extra={"reason": "TimeoutError: ", "timeout": "240"})
    assert "240" in exc.msg, "register_all 里的模板没落到这个码上"

    envelope = envelope_for(exc)
    assert envelope.code == "LLM_TIMEOUT"
    assert envelope.domain.value == "llm"
    assert envelope.retryable is True
    assert safe_message(exc) == "模型响应超时，请稍后重试。"


async def test_stream_failure_carries_the_same_envelope_fields_as_plain_calls(
    monkeypatch,
):
    """两条路径的信封字段要一致：只差在生效的上界，诊断信息不该此有彼无。"""
    _patch_client(monkeypatch, _ScriptedCompletions(["partial"], chunks=("甲",)))
    with pytest.raises(Error) as excinfo:
        async for _text in _service(timeout_retries=1).astream(_messages()):
            pass
    assert excinfo.value.extra["retry_count"] == "0"
    assert excinfo.value.extra["chunks"] == "1"
    assert excinfo.value.extra["timeout"] == "30"


class _TimingOutLLM:
    """一开口就抛带码超时的 LLM 桩（驱动 `CharacterAgent` 的包装路径）。"""

    provider = "stub"
    model = "stub"

    async def astream_with_tools(  # noqa: ANN201
        self,
        messages,  # noqa: ANN001
        *,
        tools=None,  # noqa: ANN001
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ):
        if False:  # pragma: no cover - 只为让它是个 async generator
            yield StreamChunk(content="", tool_calls=())
        raise new(codes.LLM_TIMEOUT, extra={"reason": "TimeoutError: ", "timeout": "240"})


async def test_character_agent_does_not_flatten_a_coded_timeout():
    """Agent 层再包一层 `LLM_CALL_FAILED` 会把 4004 抹成 4001，运维就看不出该调超时。"""
    agent = CharacterAgent(
        CharacterSetting(name="杜甫", public_background="诗人"),
        _TimingOutLLM(),
        _FakeWorld(),
    )
    with pytest.raises(Error) as excinfo:
        await agent.react_to(
            PlayerAction(type="text", text="走"), "stage2", on_delta=lambda _t: None
        )
    # 必须断言**顶层**码：`match_code` 会沿 cause 链找到被包进去的 4004，
    # 拿它断言的话，即使这里又包了一层 4001 也照样通过（假绿）。
    assert excinfo.value.code == codes.LLM_TIMEOUT


# ===== 5. 教师端看得到什么 =====


def test_generation_progress_surfaces_a_readable_timeout():
    """#65 的现象：教师端只看到「4001」一个数字，看不出发生了什么。

    `GenerationProgress.error` 是生成失败时教师唯一能看到的文案。
    """
    from app.services.script_library import _failure_text

    exc = new(codes.LLM_TIMEOUT, extra={"reason": "TimeoutError: ", "timeout": "240"})
    text = _failure_text(exc)
    assert text == "LLM_TIMEOUT：模型响应超时，请稍后重试。"

    # 不带码的异常仍保留自身措辞（否则真实原因会被笼统的「服务内部错误」盖掉）。
    assert _failure_text(_QuietError()) == "_QuietError: "
