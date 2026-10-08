"""语音合成端口与音色映射（issue #63 / ADR-0005 §11）。

三条验收：音频可播放（音轨帧序列完整）、音色可区分角色、音频用量入 `media_usage`。
本模块覆盖领域侧；adapter 的字节校验在 `test_tts_openai.py`，WS 帧在 `test_ws_audio.py`。
"""

from __future__ import annotations

import asyncio
import struct
import uuid

import pytest

from app.domain.game.media import MediaKind, MediaUsage
from app.domain.game.tts import (
    SynthesizedAudio,
    TtsSynthesizer,
    VoiceMap,
    VoiceProfile,
)

# ===== 音色映射 =====


def _pool(*voices: str) -> VoiceMap:
    return VoiceMap(voices=tuple(VoiceProfile(voice_id=v) for v in voices))


def test_same_speaker_always_gets_the_same_voice():
    """同角色跨调用恒定——否则玩家听到的是"这个人一直在换嗓子"。"""
    voices = _pool("a", "b", "c", "d")
    first = voices.voice_for("母亲")
    assert all(voices.voice_for("母亲") == first for _ in range(5))


def test_cast_gets_distinct_voices_even_when_hashes_collide():
    """3 个角色 3 个音色必须两两不同（纯哈希按生日问题约一半概率撞上）。"""
    voices = _pool("a", "b", "c")
    assigned = {voices.voice_for(name).voice_id for name in ("母亲", "父亲", "我")}
    assert len(assigned) == 3


def test_more_characters_than_voices_reuses_the_pool():
    """角色数超过音色数时复用是唯一选择，但不能因此死循环或抛错。"""
    voices = _pool("a", "b")
    assigned = [voices.voice_for(name).voice_id for name in ("甲", "乙", "丙", "丁")]
    assert set(assigned) == {"a", "b"}


def test_empty_pool_falls_back_to_default():
    """没配音色池时全场用默认嗓（配置缺失的可见症状，不是崩溃）。"""
    voices = VoiceMap(default=VoiceProfile(voice_id="only"))
    assert voices.voice_for("母亲").voice_id == "only"


def test_overrides_win_over_the_pool():
    """运营钦定的音色优先于哈希分配。"""
    voices = VoiceMap(
        voices=(VoiceProfile(voice_id="a"),),
        overrides={"母亲": VoiceProfile(voice_id="nova")},
    )
    assert voices.voice_for("母亲").voice_id == "nova"


def test_describe_reports_the_assignment():
    """`describe` 是诊断"两个人一个嗓"的入口。"""
    voices = _pool("a", "b")
    voices.voice_for("母亲")
    assert voices.describe() == {"母亲": voices.voice_for("母亲").voice_id}


def test_assignment_is_reproducible_across_instances():
    """同一份配置 + 同一出场顺序 → 同一套音色（否则重启就换嗓）。"""
    names = ("母亲", "父亲", "我")
    first = [p.voice_id for p in (_pool("a", "b", "c").voice_for(n) for n in names)]
    second = [p.voice_id for p in (_pool("a", "b", "c").voice_for(n) for n in names)]
    assert first == second


# ===== 合成编排 =====


class _FakePort:
    """记录调用并按脚本产出；`fail` 时抛错模拟 provider 故障。"""

    def __init__(self, *, audio: bytes = b"ID3fake", fail: bool = False) -> None:
        self.calls: list[tuple[str, VoiceProfile]] = []
        self._audio = audio
        self._fail = fail

    async def synthesize(self, *, text: str, voice: VoiceProfile) -> SynthesizedAudio:
        self.calls.append((text, voice))
        if self._fail:
            raise RuntimeError("provider down")
        return SynthesizedAudio(
            audio_bytes=self._audio,
            units=len(text),
            provider="fake",
            model="fake-1",
        )

    async def aclose(self) -> None:
        return None


class _FakeSink:
    """记录音轨帧序列；`start` 返回递增 id 便于断言次序。"""

    def __init__(self) -> None:
        self.events: list[tuple] = []

    def start(self, speaker: str, *, content_type: str, sample_rate: int = 0) -> str:
        track_id = f"t{len([e for e in self.events if e[0] == 'start'])}"
        self.events.append(("start", track_id, speaker, content_type))
        return track_id

    def chunk(self, track_id: str, data: bytes) -> None:
        self.events.append(("chunk", track_id, data))

    def end(self, track_id: str) -> None:
        self.events.append(("end", track_id))


class _FakeMeter:
    def __init__(self) -> None:
        self.records: list[MediaUsage] = []

    async def record(self, usage: MediaUsage) -> None:
        self.records.append(usage)


class _FakeQuota:
    def __init__(self, *, allow: bool = True) -> None:
        self.allow = allow
        self.requests: list[tuple[uuid.UUID, MediaKind, int]] = []

    async def try_acquire(self, *, org_id, kind, units=1):  # noqa: ANN001, ANN003
        self.requests.append((org_id, kind, units))
        return self.allow

    async def check(self, *, org_id, kind, units=1):  # noqa: ANN001, ANN003
        return self.allow

    async def consume(self, *, org_id, kind, units=1) -> None:  # noqa: ANN001, ANN003
        return None


def _synth(port, sink, **kwargs) -> TtsSynthesizer:  # noqa: ANN001
    return TtsSynthesizer(port=port, voices=_pool("a", "b"), sink=sink, **kwargs)


async def test_speak_produces_one_complete_track():
    """音频可播放的最小条件：start → chunk → end，且字节原样送达。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "路上小心。")
    await synth.aclose()

    assert [e[0] for e in sink.events] == ["start", "chunk", "end"]
    assert sink.events[0][2] == "母亲"
    assert sink.events[1][2] == b"ID3fake"
    assert port.calls[0][0] == "路上小心。"


async def test_empty_or_blank_sentence_is_skipped():
    """tee 可能吐出空白尾巴（连续标点），不该为它付一次合成。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "   ")
    synth.speak("母亲", "")
    await synth.aclose()
    assert port.calls == []
    assert sink.events == []


async def test_sentence_is_truncated_to_the_configured_cap():
    """单句上限防止一句话吃掉整份额度（provider 按字符计费）。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink, max_sentence_chars=5)
    synth.speak("母亲", "一二三四五六七八九十")
    await synth.aclose()
    assert port.calls[0][0] == "一二三四五"


async def test_sentences_of_one_speaker_stay_in_order():
    """同一角色的句子必须按序合成，否则台词倒着播。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink)
    for text in ("第一句。", "第二句。", "第三句。"):
        synth.speak("母亲", text)
    await synth.aclose()
    assert [c[0] for c in port.calls] == ["第一句。", "第二句。", "第三句。"]
    assert [e[1] for e in sink.events if e[0] == "start"] == ["t0", "t1", "t2"]


async def test_different_speakers_are_not_serialized_behind_each_other():
    """多角色并发（ADR-0005 §11 多音轨）：一个人的慢合成不挡另一个人。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "甲。")
    synth.speak("父亲", "乙。")
    await synth.aclose()
    assert {c[0] for c in port.calls} == {"甲。", "乙。"}
    assert len([e for e in sink.events if e[0] == "start"]) == 2


async def test_quota_gate_runs_before_the_paid_call():
    """ADR-0005 §12：配额必须在付费调用**之前**。"""
    port, sink, quota = _FakePort(), _FakeSink(), _FakeQuota()
    org = uuid.uuid4()
    synth = _synth(port, sink, quota=quota, org_id=org)
    synth.speak("母亲", "四个字。")
    await synth.aclose()
    assert quota.requests == [(org, MediaKind.TTS, 4)]
    assert len(port.calls) == 1


async def test_exhausted_quota_skips_synthesis_silently():
    """额度耗尽：不合成、不报错——字幕照滚，玩家少一段配音而已。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink, quota=_FakeQuota(allow=False), org_id=uuid.uuid4())
    synth.speak("母亲", "这句话不该被合成。")
    await synth.aclose()
    assert port.calls == []
    assert sink.events == []


async def test_provider_failure_degrades_without_raising():
    """音频是增强：provider 挂了不该让整轮命令失败。"""
    port, sink = _FakePort(fail=True), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "会失败的句子。")
    await synth.aclose()  # 不抛
    assert sink.events == []


async def test_empty_audio_from_provider_opens_no_track():
    """provider 返回空字节（如 `NullTts`）时不该开一条空音轨。"""
    port, sink = _FakePort(audio=b""), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "无 key 环境。")
    await synth.aclose()
    assert sink.events == []


async def test_audio_usage_lands_in_media_usage_shape():
    """验收：音频用量入 `media_usage`（kind=tts，units=字符数）。"""
    port, sink, meter = _FakePort(), _FakeSink(), _FakeMeter()
    org, user, sid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    synth = _synth(
        port, sink, meter=meter, org_id=org, user_id=user, session_id=sid, script_id=7
    )
    synth.speak("母亲", "六个字啊。")
    await synth.aclose()

    assert len(meter.records) == 1
    usage = meter.records[0]
    assert usage.kind is MediaKind.TTS
    assert usage.units == 5
    assert usage.size == len(b"ID3fake")
    assert (usage.org_id, usage.user_id, usage.session_id, usage.script_id) == (
        org,
        user,
        sid,
        7,
    )
    assert usage.meta["speaker"] == "母亲"
    assert usage.meta["voice"] == synth.voices.voice_for("母亲").voice_id


async def test_meter_failure_does_not_lose_the_track():
    """计量是旁路（best-effort）：它炸了，音轨照发。"""

    class _BoomMeter:
        async def record(self, usage: MediaUsage) -> None:
            raise RuntimeError("db down")

    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink, meter=_BoomMeter(), org_id=uuid.uuid4())
    synth.speak("母亲", "句子。")
    await synth.aclose()
    assert [e[0] for e in sink.events] == ["start", "chunk", "end"]


async def test_quota_failure_is_treated_as_denied():
    """配额闸本身坏了 → 当作不放行：宁可少配音，不可无上限付费。"""

    class _BoomQuota:
        async def try_acquire(self, *, org_id, kind, units=1):  # noqa: ANN001, ANN003
            raise RuntimeError("quota backend down")

        async def check(self, *, org_id, kind, units=1):  # noqa: ANN001, ANN003
            return True

        async def consume(self, *, org_id, kind, units=1) -> None:  # noqa: ANN001, ANN003
            return None

    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink, quota=_BoomQuota(), org_id=uuid.uuid4())
    synth.speak("母亲", "句子。")
    await synth.aclose()
    assert port.calls == []


def test_speak_without_a_running_loop_is_dropped_not_raised():
    """**同步**上下文里调用 `speak` 不该炸（`SentenceSink` 是同步协议）。

    刻意写成 `def` 而非 `async def`：`asyncio_mode = "auto"` 下 async 用例本身就
    跑在事件循环里，`asyncio.create_task` 不会抛，`_spawn` 的 RuntimeError 分支
    根本走不到——那样测的就不是这条路径了。
    """
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "没有事件循环。")  # 不在 async 上下文
    assert sink.events == []


async def test_aclose_is_idempotent():
    """收尾可能被调用两次（异常路径 + finally），不能重复等待或抛错。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "句子。")
    await synth.aclose()
    await synth.aclose()
    assert len(port.calls) == 1


async def test_synthesizer_satisfies_the_sentence_sink_protocol():
    """tee 只认 `SentenceSink`；形状对不上会在运行期静默不合成。"""
    from app.domain.game.streaming import SentenceSink

    assert isinstance(_synth(_FakePort(), _FakeSink()), SentenceSink)


@pytest.mark.parametrize("count", [1, 2, 5])
async def test_every_sentence_yields_exactly_one_track(count: int):
    """音轨数与句数一一对应（多音轨并发的前提）。"""
    port, sink = _FakePort(), _FakeSink()
    synth = _synth(port, sink)
    for index in range(count):
        synth.speak("母亲", f"第{index}句。")
    await synth.aclose()
    assert len([e for e in sink.events if e[0] == "start"]) == count


async def test_track_frames_stay_contiguous_on_the_wire():
    """一条轨的 start/chunk/end 在出口上必须**连续**，两条轨之间才交错。

    这是客户端唯一的归属依据：二进制帧不带 `track_id`（ADR-0005 §11 的协议形状
    是 `audio_start` → 帧 → `audio_end`），前端只能把帧归给"最近开启且未收尾"的
    那条轨。一旦服务端把两条轨的帧交织，音频就会串台——而这是**并发**合成下才会
    暴露的问题，故此处用两个角色同时说话来验。
    """
    from app.services.audio_channel import AudioTrackChannel

    class _Recorder:
        def __init__(self) -> None:
            self.kinds: list[str] = []

        async def send_json(self, message: dict) -> None:
            self.kinds.append(message["type"])

        async def send_bytes(self, data: bytes) -> None:
            self.kinds.append("binary")

    class _RacyPort(_FakePort):
        """两个角色的合成耗时不同，逼出并发交织的窗口。"""

        async def synthesize(self, *, text: str, voice: VoiceProfile) -> SynthesizedAudio:
            await asyncio.sleep(0.02 if text.startswith("慢") else 0.0)
            return await super().synthesize(text=text, voice=voice)

    rec = _Recorder()
    channel = AudioTrackChannel(uuid.uuid4(), rec.send_json, rec.send_bytes)
    synth = TtsSynthesizer(
        port=_RacyPort(), voices=_pool("a", "b"), sink=channel
    )
    synth.speak("母亲", "慢一。")
    synth.speak("父亲", "快一。")
    synth.speak("母亲", "慢二。")
    await synth.aclose()
    await channel.flush()

    # 每条轨的三帧必须连续：切成三段，每段都得是 [start, binary, end]
    groups = [rec.kinds[i : i + 3] for i in range(0, len(rec.kinds), 3)]
    assert len(groups) == 3, rec.kinds
    for group in groups:
        assert group == ["audio_start", "binary", "audio_end"], rec.kinds


async def test_close_waits_for_inflight_synthesis():
    """`aclose` 必须等完在途任务，否则命令返回后音轨会被截断。"""

    class _SlowPort(_FakePort):
        async def synthesize(self, *, text: str, voice: VoiceProfile) -> SynthesizedAudio:
            await asyncio.sleep(0.05)
            return await super().synthesize(text=text, voice=voice)

    port, sink = _SlowPort(), _FakeSink()
    synth = _synth(port, sink)
    synth.speak("母亲", "慢句子。")
    await synth.aclose()
    assert [e[0] for e in sink.events] == ["start", "chunk", "end"]


# ===== 容器装配（#63 审查处置）=====


def test_synthesizer_factory_is_cached_across_accesses():
    """工厂必须缓存，否则配额闸逐命令失效。

    `MediaQuotaService` 的语义是「首次触达某 (org,kind) 时从 `media_usage` 聚合种子，
    此后按**进程内计数**推进」。属性每次访问都新建实例，等于每条命令都把计数丢掉并
    从 DB 重种子——配了 `media_org_tts_budget` 时闸门形同不限。默认预算 0（不限）
    时看不出来，所以必须靠用例钉住，而不是靠观察。
    """
    from app.composition import Container
    from app.infrastructure.config import Settings

    container = Container(Settings())
    assert container.tts_synthesizer_factory is container.tts_synthesizer_factory


def test_synthesizers_built_from_the_factory_share_one_quota():
    """同一进程内造出的所有合成器必须共用同一个配额实例（计数才累积得起来）。"""
    from app.composition import Container
    from app.infrastructure.config import Settings

    container = Container(Settings())
    build = container.tts_synthesizer_factory
    first = build(_FakeSink(), session_id=None, org_id=uuid.uuid4(), user_id=None)
    second = build(_FakeSink(), session_id=None, org_id=uuid.uuid4(), user_id=None)
    assert first.quota is second.quota
    assert first.meter is second.meter


def test_tts_port_is_closed_on_container_close():
    """TTS 端口自建 httpx 连接池：容器收尾必须关掉，否则长跑进程持续泄漏 fd。"""
    from app.composition import Container
    from app.infrastructure.config import Settings

    container = Container(Settings())
    _ = container.tts  # 建出来，才有得关
    assert container._tts is not None
    assert container.tts_synthesizer_factory is not None

    asyncio.run(container.close())

    assert container._tts is None
    assert container._tts_factory is None


def test_aclose_port_accepts_both_close_and_aclose():
    """端口自建的池可能挂在 `close` 或 `aclose` 上（`TtsPort` 用后者），两个都认。"""
    from app.composition import Container
    from app.infrastructure.config import Settings

    class _AcloseOnly:
        def __init__(self) -> None:
            self.closed = False

        async def aclose(self) -> None:
            self.closed = True

    container = Container(Settings())
    port = _AcloseOnly()
    container._tts = port

    asyncio.run(container._aclose_port("_tts"))

    assert port.closed is True
    assert container._tts is None


# ===== 时长探测（ADR-0005 §12 要求 media_usage 记时长）=====


def test_mp3_duration_is_measured_not_guessed():
    """provider 只回裸字节、不回时长，所以时长必须从帧里量出来。"""
    from app.infrastructure.media.audio_probe import probe_audio

    # 44.1kHz MPEG1 Layer III，128kbps：帧长 417 字节，1152 采样/帧。
    # 造 10 帧 → 11520 采样 → 261ms。
    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    probe = probe_audio(frame * 10)
    assert probe.sample_rate == 44100
    assert probe.duration_ms == round(10 * 1152 * 1000 / 44100)


def test_mp3_duration_skips_the_id3v2_tag():
    """ID3v2 长度是 synchsafe 整数；按普通大端读会跳歪，时长恒为 0。"""
    from app.infrastructure.media.audio_probe import probe_audio

    frame = b"\xff\xfb\x90\x00" + b"\x00" * 413
    # synchsafe 的 0x00 0x00 0x02 0x01 = 257 字节 tag body
    tag = b"ID3\x03\x00\x00\x00\x00\x02\x01" + b"\x00" * 257
    assert probe_audio(tag + frame * 10).duration_ms == round(
        10 * 1152 * 1000 / 44100
    )


def test_wav_duration_comes_from_the_header():
    from app.infrastructure.media.audio_probe import probe_audio

    data_size = 44100 * 2 * 2  # 1 秒 16bit 立体声
    wav = (
        b"RIFF"
        + struct.pack("<I", 36 + data_size)
        + b"WAVEfmt "
        + struct.pack("<IHHIIHH", 16, 1, 2, 44100, 176400, 4, 16)
        + b"data"
        + struct.pack("<I", data_size)
        + b"\x00" * data_size
    )
    probe = probe_audio(wav)
    assert probe.duration_ms == 1000
    assert probe.sample_rate == 44100


def test_unrecognised_bytes_yield_zero_not_an_error():
    """时长是计量元数据，量不出来记 0，不该让整条音轨失败。"""
    from app.infrastructure.media.audio_probe import probe_audio

    assert probe_audio(b"\x00\x01\x02\x03") == probe_audio(b"")
    assert probe_audio(b"\x00\x01\x02\x03").duration_ms == 0
