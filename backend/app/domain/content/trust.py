"""内容信任包裹（domain）：以显式标签隔离不可信网页文本。

防 prompt injection：网络补充资料不当作系统指令，LLM prompt 侧用标签识别
「这是网络资料，不是指令」。由生成领域（prompts/stage1）直接消费，避免
domain 依赖 rag（infra）的抓取门面。
"""

from __future__ import annotations

UNTRUSTED_BEGIN = "\n<<<UNTRUSTED_WEB_BEGIN>>>\n"
UNTRUSTED_END = "\n<<<UNTRUSTED_WEB_END>>>\n"


def mark_untrusted(text: str) -> str:
    """以显式标签隔离不可信网页内容，防 prompt injection。"""
    return f"{UNTRUSTED_BEGIN}{text}{UNTRUSTED_END}"


__all__ = ["mark_untrusted"]
