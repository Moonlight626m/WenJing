"""错误构造与匹配辅助函数。

- `new(code, extra=...)`：从错误码创建新错误（等价 Go 的 `New`）
- `wrap(cause, code, extra=...)`：把已有异常包装为带错误码的错误（等价 Go 的 `WrapByCode`）
- `match_code(err, code)`：判断异常（含 cause 链）是否匹配某错误码（等价 Go 的 `errors.Is`）
"""

from __future__ import annotations

from app.infrastructure.errx.error import Error


def new(
    code: int,
    *,
    cause: BaseException | None = None,
    extra: dict[str, str] | None = None,
) -> Error:
    return Error(code, cause=cause, extra=extra)


def wrap(
    cause: BaseException,
    code: int,
    *,
    extra: dict[str, str] | None = None,
) -> Error:
    return Error(code, cause=cause, extra=extra)


def match_code(err: BaseException, code: int) -> bool:
    """沿异常链（Python `__cause__` + errorx 的 `Error.cause`）判断是否含指定错误码。"""
    current: BaseException | None = err
    while current is not None:
        if isinstance(current, Error) and current.code == code:
            return True
        if isinstance(current, Error) and current.cause is not None:
            current = current.cause if isinstance(current.cause, BaseException) else None
            continue
        current = current.__cause__
    return False
