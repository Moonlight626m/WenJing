"""文境统一错误体系（errx）。

仿 github.com/xh-polaris/psych-post/pkg/errorx：
- 集中注册错误码（`codes.py`）
- `Error` 携带 code / message / extra / cause / stack / is_affect_stability
- `new` / `wrap` 构造错误，`match_code` 沿原因链匹配

用法::

    from app.infrastructure.errx import codes, new, wrap, match_code

    raise new(codes.ENG_INVALID_TRANSITION, extra={"src": "a", "dst": "b"})
    try:
        ...
    except Exception as e:
        raise wrap(e, codes.LLM_CALL_FAILED, extra={"reason": str(e)}) from e
    # 匹配（含 cause 链）：
    if match_code(exc, codes.LLM_CALL_FAILED):
        ...
"""

from __future__ import annotations

from app.infrastructure.errx import codes
from app.infrastructure.errx._factory import match_code, new, wrap
from app.infrastructure.errx._registry import (
    CodeDefinition,
    all_definitions,
    default_error_code,
    lookup,
    register,
    set_default_error_code,
)
from app.infrastructure.errx.error import Error

# 导入即注册全部错误码（幂等）
codes.register_all()

__all__ = [
    "Error",
    "CodeDefinition",
    "new",
    "wrap",
    "match_code",
    "register",
    "lookup",
    "all_definitions",
    "set_default_error_code",
    "default_error_code",
    "codes",
]
