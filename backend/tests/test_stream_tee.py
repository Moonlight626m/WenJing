"""流式 tee 编排测试（issue #62 / ADR-0005 §10）。

一个入口（`SpeechStreamSink`）、两个出口：逐字给 WS 文本，攒够一句给 TTS 出口。
不起 DB、不起 WS：两个出口都是最小假实现，只断言分流本身。
"""

from __future__ import annotations

from app.domain.game.streaming import (
    SentenceSink,
    SpeechStreamSink,
    StreamTee,
    TextDelta,
)


class _TextSink:
    """WS 文本出口的假实现。"""

    def __init__(self) -> None:
        self.started: list[tuple[str, str]] = []
        self.deltas: list[tuple[str, str]] = []
        self.ended: list[str] = []

    def start(self, speaker: str) -> str:
        stream_id = f"s{len(self.started) + 1}"
        self.started.append((stream_id, speaker))
        return stream_id

    def delta(self, stream_id: str, text: str) -> None:
        self.deltas.append((stream_id, text))

    def end(self, stream_id: str) -> None:
        self.ended.append(stream_id)


class _SentenceSink:
    """TTS 出口（M6 #63 的占位）的假实现。"""

    def __init__(self) -> None:
        self.said: list[tuple[str, str]] = []

    def speak(self, speaker: str, sentence: str) -> None:
        self.said.append((speaker, sentence))


def test_tee_satisfies_the_sink_protocol():
    """运行时只认 `speech_sink` 这一个出口，tee 必须长得像它。"""
    assert isinstance(StreamTee(), SpeechStreamSink)
    assert isinstance(_SentenceSink(), SentenceSink)


async def test_deltas_pass_through_verbatim():
    text = _TextSink()
    tee = StreamTee(text_sink=text)

    stream_id = tee.start("母亲")
    tee.delta(stream_id, "路上")
    tee.delta(stream_id, "小心")
    tee.end(stream_id)

    assert text.started == [(stream_id, "母亲")]
    assert text.deltas == [(stream_id, "路上"), (stream_id, "小心")]
    assert text.ended == [stream_id]


async def test_sentences_are_emitted_only_when_complete():
    sentences = _SentenceSink()
    tee = StreamTee(sentence_sink=sentences)
    stream_id = tee.start("母亲")

    tee.delta(stream_id, "路上小心，")  # 逗号是句内停顿，不是分句点
    assert sentences.said == [], "没到句末标点不该开口"
    tee.delta(stream_id, "药买了")
    tee.delta(stream_id, "就回来。")
    assert sentences.said == [("母亲", "路上小心，药买了就回来。")]

    tee.delta(stream_id, "记住了吗？！")
    assert sentences.said[-1] == ("母亲", "记住了吗？！"), "连续标点算同一句"


async def test_end_flushes_the_unterminated_tail():
    sentences = _SentenceSink()
    tee = StreamTee(sentence_sink=sentences)
    stream_id = tee.start("母亲")
    tee.delta(stream_id, "你")

    tee.end(stream_id)

    assert sentences.said == [("母亲", "你")]


async def test_end_without_leftover_says_nothing():
    sentences = _SentenceSink()
    tee = StreamTee(sentence_sink=sentences)
    stream_id = tee.start("母亲")
    tee.delta(stream_id, "路上小心。")

    tee.end(stream_id)

    assert sentences.said == [("母亲", "路上小心。")]


async def test_concurrent_streams_do_not_share_sentence_state():
    """多角色并发生成：各 stream_id 各攒各的，尾巴不串台。"""
    sentences = _SentenceSink()
    tee = StreamTee(sentence_sink=sentences)
    first = tee.start("母亲")
    second = tee.start("我")

    tee.delta(first, "路上")
    tee.delta(second, "我")
    tee.delta(first, "小心。")
    tee.delta(second, "走了。")

    assert sentences.said == [("母亲", "路上小心。"), ("我", "我走了。")]
    tee.end(first)
    tee.end(second)
    assert sentences.said == [("母亲", "路上小心。"), ("我", "我走了。")]


async def test_push_fans_out_and_keeps_the_bounded_buffer():
    text = _TextSink()
    sentences = _SentenceSink()
    tee = StreamTee(text_sink=text, sentence_sink=sentences, max_buffer=2)

    for index in range(4):
        tee.push(TextDelta(stream_id="s", speaker="甲", text=f"{index}。"))

    assert [d.text for d in tee.drain()] == ["2。", "3。"], "缓冲 drop-oldest"
    assert [t for _, t in text.deltas] == ["0。", "1。", "2。", "3。"], "文本出口不丢字"
    assert sentences.said == [("甲", "0。"), ("甲", "1。"), ("甲", "2。"), ("甲", "3。")]


async def test_tee_without_outlets_is_a_no_op():
    """两个出口都可缺省：没接消费方时 tee 不该炸，只留缓冲。"""
    tee = StreamTee()
    stream_id = tee.start("母亲")
    tee.delta(stream_id, "路上小心。")
    tee.end(stream_id)

    assert [d.text for d in tee.drain()] == ["路上小心。"]
