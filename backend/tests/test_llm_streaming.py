"""LLM 流式端口测试（issue #58 / ADR-0005 §10）。

无 DB 依赖：用 scripted 内层 LLM + 捕获式 recorder 验证逐段产出与一次往返一条计量。
"""

from __future__ import annotations

import contextlib
import uuid

from app.contracts.enums import UsagePurpose
from app.infrastructure.llm.chat import ChatLLMService, _delta_content
from app.infrastructure.usage import UsageContext, UsageRecordingLLM


class _ScriptedLLM:
    """按脚本逐段产出的内层 LLM。"""

    provider = "scripted"
    model = "scripted-1"

    def __init__(self, chunks: list[str], *, fail_at: int | None = None) -> None:
        self.chunks = chunks
        self.fail_at = fail_at
        self.chat_calls = 0

    async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        self.chat_calls += 1
        return "".join(self.chunks)

    async def astream(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        for i, chunk in enumerate(self.chunks):
            if self.fail_at is not None and i == self.fail_at:
                raise RuntimeError("boom")
            yield chunk


class _NoStreamLLM:
    """只实现 chat 的旧式内层，验证降级路径。"""

    provider = "nostream"
    model = "nostream-1"

    async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        return "整段回答"


class _CaptureRecorder:
    """不落库、捕获每次计量调用参数的假 recorder。"""

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def record(self, context, **kwargs):  # noqa: ANN001
        self.calls.append({"context": context, **kwargs})


def _ctx() -> UsageContext:
    return UsageContext(org_id=uuid.uuid4(), user_id=uuid.uuid4())


async def test_streaming_yields_chunks_in_order():
    llm = UsageRecordingLLM(
        _ScriptedLLM(["你", "好", "，", "世界"]),
        recorder=_CaptureRecorder(),
        context=_ctx(),
    )
    out = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]
    assert out == ["你", "好", "，", "世界"]


async def test_streaming_records_one_row_with_accumulated_text():
    recorder = _CaptureRecorder()
    llm = UsageRecordingLLM(
        _ScriptedLLM(["甲", "乙", "丙"]),
        recorder=recorder,
        context=_ctx(),
    )
    [c async for c in llm.astream(
        [{"role": "user", "content": "x"}], purpose=UsagePurpose.VERIFY
    )]
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call["completion"] == "甲乙丙"
    assert call["purpose"] is UsagePurpose.VERIFY
    assert call["provider"] == "scripted"


async def test_streaming_degrades_when_inner_has_no_astream():
    recorder = _CaptureRecorder()
    llm = UsageRecordingLLM(
        _NoStreamLLM(),
        recorder=recorder,
        context=_ctx(),
    )
    out = [c async for c in llm.astream([{"role": "user", "content": "hi"}])]
    assert out == ["整段回答"]
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["completion"] == "整段回答"


async def test_streaming_records_partial_when_consumer_stops_early():
    recorder = _CaptureRecorder()
    llm = UsageRecordingLLM(
        _ScriptedLLM(["一", "二", "三"]),
        recorder=recorder,
        context=_ctx(),
    )
    agen = llm.astream([{"role": "user", "content": "x"}])
    assert await anext(agen) == "一"
    await agen.aclose()
    assert len(recorder.calls) == 1
    assert recorder.calls[0]["completion"] == "一"


async def test_streaming_records_partial_on_failure():
    recorder = _CaptureRecorder()
    llm = UsageRecordingLLM(
        _ScriptedLLM(["一", "二", "三"], fail_at=2),
        recorder=recorder,
        context=_ctx(),
    )
    seen: list[str] = []
    try:
        async for chunk in llm.astream([{"role": "user", "content": "x"}]):
            seen.append(chunk)
    except RuntimeError:
        pass
    else:  # pragma: no cover - 防御：断言必须抛错
        raise AssertionError("脚本应在第 2 段抛错")
    assert seen == ["一", "二"]
    assert recorder.calls[0]["completion"] == "一二"


async def test_no_record_when_stream_fails_before_any_output():
    """产出任何内容前失败：不写幻影计量（与非流式 chat 一致）。"""
    recorder = _CaptureRecorder()
    llm = UsageRecordingLLM(
        _ScriptedLLM(["一"], fail_at=0),
        recorder=recorder,
        context=_ctx(),
    )
    try:
        [c async for c in llm.astream([{"role": "user", "content": "x"}])]
    except RuntimeError:
        pass
    else:  # pragma: no cover - 防御
        raise AssertionError("脚本应在首段抛错")
    assert recorder.calls == []


def test_delta_content_ignores_non_content_chunks():
    class _Delta:
        def __init__(self, content):  # noqa: ANN001
            self.content = content

    class _Choice:
        def __init__(self, delta):  # noqa: ANN001
            self.delta = delta

    class _Chunk:
        def __init__(self, choices):  # noqa: ANN001
            self.choices = choices

    assert _delta_content(_Chunk([_Choice(_Delta("你好"))])) == "你好"
    assert _delta_content(_Chunk([_Choice(_Delta(None))])) == ""
    assert _delta_content(_Chunk([])) == ""


class _StreamChunk:
    def __init__(self, text: str) -> None:
        self.choices = [type("C", (), {"delta": type("D", (), {"content": text})()})()]


class _FakeStream:
    def __init__(self, chunks: list[str]) -> None:
        self._chunks = iter(chunks)

    def __aiter__(self):  # noqa: ANN204
        return self

    async def __anext__(self):  # noqa: ANN204
        try:
            return _StreamChunk(next(self._chunks))
        except StopIteration:
            raise StopAsyncIteration


class _FakeMessage:
    content = "完整答复"
    tool_calls = None


class _FakeResponse:
    choices = [type("C", (), {"message": _FakeMessage()})()]
    usage = None


class _FakeCompletions:
    def __init__(self, *, stream_chunks: list[str] | None = None) -> None:
        self.stream_chunks = stream_chunks
        self.kwargs: dict | None = None

    async def create(self, **kwargs):  # noqa: ANN003, ANN201
        self.kwargs = kwargs
        if kwargs.get("stream"):
            return _FakeStream(self.stream_chunks or [])
        return _FakeResponse()


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions
        self.chat = type("Chat", (), {"completions": completions})()


def _patch_client(monkeypatch, completions: _FakeCompletions) -> None:
    from app.infrastructure.llm.chat import ChatLLMService

    client = _FakeClient(completions)

    @contextlib.asynccontextmanager
    async def fake_client(self, session_id):  # noqa: ANN001, ANN202
        yield client

    monkeypatch.setattr(ChatLLMService, "_client", fake_client)


def _service() -> ChatLLMService:
    return ChatLLMService(model="m", api_key="k", provider="openai")


async def test_chatllm_astream_passes_stream_kwargs(monkeypatch):
    completions = _FakeCompletions(stream_chunks=["甲", "乙"])
    _patch_client(monkeypatch, completions)
    out = [c async for c in _service().astream([{"role": "user", "content": "x"}])]
    assert out == ["甲", "乙"]
    assert completions.kwargs is not None
    assert completions.kwargs["stream"] is True
    assert completions.kwargs["model"] == "m"
    assert "messages" in completions.kwargs


async def test_chatllm_chat_unpacks_request_as_keywords(monkeypatch):
    """回归：请求体必须解包为关键字参数（曾以位置参数传入 dict 导致 TypeError）。"""
    completions = _FakeCompletions()
    _patch_client(monkeypatch, completions)
    out = await _service().chat([{"role": "user", "content": "x"}])
    assert out == "完整答复"
    assert completions.kwargs is not None
    assert "stream" not in completions.kwargs
    assert completions.kwargs["model"] == "m"
