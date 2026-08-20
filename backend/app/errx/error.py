"""StatusError 的 Python 实现：携带错误码、消息、原因、调用栈与扩展元数据。

仿 github.com/xh-polaris/psych-post/pkg/errorx。与 Go 版等价：
- `Error` 即 StatusError（code / message / extra / is_affect_stability）
- `cause` 保留原始异常，形成原因链
- `stack` 记录错误创建点的调用栈
- 消息支持 `{key}` 占位符，由 `extra` 替换
"""

from __future__ import annotations

import traceback
from typing import Any

from app.errx import _registry


class Error(Exception):
    """携带标准错误码的异常。全项目的统一错误类型。"""

    def __init__(
        self,
        code: int,
        message: str | None = None,
        *,
        cause: BaseException | None = None,
        extra: dict[str, str] | None = None,
        capture_stack: bool = True,
    ) -> None:
        self.code = code
        self._message = message if message is not None else _registry.lookup(code).message
        self.cause = cause
        self.extra: dict[str, str] = dict(extra) if extra else {}
        self.is_affect_stability = _registry.lookup(code).is_affect_stability
        self.stack = traceback.format_stack()[:-1] if capture_stack else ""
        self._message = self._format_message(self._message, self.extra)
        super().__init__(self._build_string())

    @staticmethod
    def _format_message(message: str, extra: dict[str, str]) -> str:
        for key, value in extra.items():
            message = message.replace("{" + key + "}", value)
        return message

    def _build_string(self) -> str:
        parts = [f"code={self.code} message={self._message}"]
        if self.cause is not None:
            parts.append(f"cause={self.cause}")
        if self.stack:
            parts.append("stack=" + "".join(self.stack))
        return "\n".join(parts)

    @property
    def msg(self) -> str:
        return self._message

    def stack_trace(self) -> str:
        return self.stack

    def __reduce__(self) -> tuple[Any, tuple[int, str]]:
        # 保证异常可被 pickle（asyncio / 多进程场景）
        return (Error, (self.code, self._message))
