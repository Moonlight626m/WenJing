"""LLM 原始输出 → JSON 文本提取（stage1 与 workflow 共用）。"""

from __future__ import annotations

import re

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json(raw: str) -> str:
    """从 LLM 输出中提取 JSON 文本：剥掉 markdown 围栏或夹杂的解释文字。"""
    text = raw.strip()
    fenced = _JSON_FENCE_RE.match(text)
    if fenced:
        return fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text
