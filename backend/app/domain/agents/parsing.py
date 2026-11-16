"""LLM 输出解析：从自由文本里取出 JSON 对象。

运行期 Agent（Director / WorldBuilder / Verifier）都要求「只输出一个 JSON 对象」，
但模型偶尔会包 ```json 代码块或前后加说明；这里统一容忍这些噪声。
"""

from __future__ import annotations

import json
import re
from typing import Any

_JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)


def extract_json_object(raw: str) -> dict[str, Any] | None:
    """取出文本里的第一个 JSON 对象（容忍 ```json 代码块与前后说明文字）。"""
    match = _JSON_OBJECT.search(raw or "")
    if not match:
        return None
    try:
        obj = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
