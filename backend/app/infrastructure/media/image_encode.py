"""生成图字节 → base64 data URL（媒体视觉链路共用）。"""

from __future__ import annotations

import base64


def sniff_mime(data: bytes) -> str:
    """按魔数识别常见图片 MIME；识别不出按 png（data URL 的 mime 错主要影响
    老旧解析器，主流 provider 宽容）。"""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    return "image/png"


def data_url(data: bytes) -> str:
    return f"data:{sniff_mime(data)};base64,{base64.b64encode(data).decode()}"
