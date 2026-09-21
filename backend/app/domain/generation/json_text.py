"""LLM 原始输出 → JSON 文本提取（stage1 与 workflow 共用）。"""

from __future__ import annotations

import re

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def extract_json(raw: str) -> str:
    """从 LLM 输出中提取 JSON 文本：剥掉 markdown 围栏或夹杂的解释文字。

    围栏内也做花括号截取兜底：真实 LLM 偶发在围栏内 JSON 之后追加
    杂散字符（曾致 trailing characters 解析失败），截取到最后一对花括号。
    """
    text = raw.strip()
    fenced = _JSON_FENCE_RE.match(text)
    if fenced:
        text = fenced.group(1)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        return text[start : end + 1]
    return text
