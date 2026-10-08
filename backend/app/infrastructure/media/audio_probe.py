"""音频字节的时长/采样率探测（issue #63）。

`media_usage` 要记音频的**时长**（ADR-0005 §12），但 provider 的响应体是**裸音频
字节**，没有时长字段——OpenAI 兼容的 `/audio/speech` 不回任何元数据。所以时长只能
从字节里量出来。

为什么不信"按码率估算"：VBR 编码下 `size/bitrate` 会差出成倍。这里的做法是
**逐帧累加采样数**——MP3 每帧的采样数由版本决定（MPEG1 Layer III 是 1152，
MPEG2/2.5 是 576），累加后除以采样率即精确时长，CBR/VBR 都对。WAV 直接读
`fmt ` 与 `data` 块算，更简单也更准。

认不出的格式返回 0：时长是**计量元数据**，量不出来不该让整条音轨失败。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# MPEG1 Layer III 每帧采样数；MPEG2/2.5 Layer III 减半。
_SAMPLES_PER_FRAME_V1 = 1152
_SAMPLES_PER_FRAME_V2 = 576

# 比特率表（kbps，索引 0 是 "free"，15 是 "bad"）
_BITRATES_V1_L3 = (
    0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0,
)
_BITRATES_V2_L3 = (
    0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0,
)
# 采样率表：索引 3 是保留值
_SAMPLE_RATES = {
    3: (44100, 48000, 32000),  # MPEG1
    2: (22050, 24000, 16000),  # MPEG2
    0: (11025, 12000, 8000),   # MPEG2.5
}


@dataclass(frozen=True)
class AudioProbe:
    """探测结果；量不出来时两个字段都是 0（不是错误）。"""

    duration_ms: int = 0
    sample_rate: int = 0


def probe_audio(data: bytes) -> AudioProbe:
    """按容器嗅探时长与采样率；认不出返回全 0。"""
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WAVE":
        return _probe_wav(data)
    if data.startswith(b"ID3") or data[:2] in (b"\xff\xfb", b"\xff\xf3", b"\xff\xf2"):
        return _probe_mp3(data)
    return AudioProbe()


def _probe_wav(data: bytes) -> AudioProbe:
    """遍历 RIFF 块找 `fmt `（采样率）与 `data`（字节数）。"""
    sample_rate = 0
    byte_rate = 0
    data_size = 0
    offset = 12
    while offset + 8 <= len(data):
        chunk_id = data[offset : offset + 4]
        size = struct.unpack_from("<I", data, offset + 4)[0]
        body = offset + 8
        if chunk_id == b"fmt " and size >= 16 and body + 16 <= len(data):
            sample_rate = struct.unpack_from("<I", data, body + 4)[0]
            byte_rate = struct.unpack_from("<I", data, body + 8)[0]
        elif chunk_id == b"data":
            # 声明长度可能超过实际字节（截断的响应），取小的那个
            data_size = min(size, max(0, len(data) - body))
            break
        # 块长为奇数时有一字节 padding
        offset = body + size + (size & 1)
    if not sample_rate or not byte_rate:
        return AudioProbe()
    return AudioProbe(
        duration_ms=round(data_size * 1000 / byte_rate), sample_rate=sample_rate
    )


def _skip_id3v2(data: bytes) -> int:
    """跳过 ID3v2 头，返回第一个音频帧的偏移。

    ID3v2 的长度是 **synchsafe** 整数（每字节只用低 7 位）——按普通大端读会多跳，
    把帧头读歪，于是时长恒为 0。
    """
    if not data.startswith(b"ID3") or len(data) < 10:
        return 0
    size_bytes = data[6:10]
    if any(b & 0x80 for b in size_bytes):
        return 0  # 非法 synchsafe：当作没有 tag
    size = 0
    for byte in size_bytes:
        size = (size << 7) | byte
    offset = 10 + size
    if data[5] & 0x10:  # footer present
        offset += 10
    return offset if 0 <= offset < len(data) else 0


def _probe_mp3(data: bytes) -> AudioProbe:
    """逐帧累加采样数：`总采样 / 采样率` = 时长（CBR/VBR 都精确）。"""
    offset = _skip_id3v2(data)
    total_samples = 0
    sample_rate = 0
    frames = 0
    length = len(data)
    while offset + 4 <= length:
        if data[offset] != 0xFF or (data[offset + 1] & 0xE0) != 0xE0:
            offset += 1  # 不同步：滑动一字节重新找帧头
            continue
        header = data[offset + 1]
        version_bits = (header >> 3) & 0x03
        layer_bits = (header >> 1) & 0x03
        if version_bits == 1 or layer_bits == 0:
            offset += 1  # 保留值
            continue
        if layer_bits != 1:  # 只处理 Layer III（我们只产出 mp3）
            offset += 1
            continue
        bitrate_index = (data[offset + 2] >> 4) & 0x0F
        rate_index = (data[offset + 2] >> 2) & 0x03
        padding = (data[offset + 2] >> 1) & 0x01
        if rate_index == 3 or bitrate_index in (0, 15):
            offset += 1
            continue
        rates = _SAMPLE_RATES.get(version_bits)
        if rates is None:
            offset += 1
            continue
        rate = rates[rate_index]
        is_v1 = version_bits == 3
        bitrate = (_BITRATES_V1_L3 if is_v1 else _BITRATES_V2_L3)[bitrate_index] * 1000
        if not bitrate or not rate:
            offset += 1
            continue
        # MPEG1 Layer III 帧长系数 144，MPEG2/2.5 是 72
        frame_length = (144 if is_v1 else 72) * bitrate // rate + padding
        if frame_length <= 4:
            offset += 1
            continue
        total_samples += _SAMPLES_PER_FRAME_V1 if is_v1 else _SAMPLES_PER_FRAME_V2
        sample_rate = sample_rate or rate
        frames += 1
        offset += frame_length
    if not frames or not sample_rate:
        return AudioProbe()
    return AudioProbe(
        duration_ms=round(total_samples * 1000 / sample_rate), sample_rate=sample_rate
    )


__all__ = ["AudioProbe", "probe_audio"]
