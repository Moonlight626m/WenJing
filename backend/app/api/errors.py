"""REST 错误 envelope 映射（唯一出口）。

`_error_response` 从 routes.py 抽出，供路由层与全局异常处理器共用。
"""

from __future__ import annotations

from fastapi.responses import JSONResponse

from app.errx import Error as WJError

# 稳定码 → HTTP 状态（未登记：不可重试 400 / 可重试 503）
_STATUS_BY_CODE: dict[str, int] = {
    "SESSION_NOT_FOUND": 404,
    "SESSION_CONFLICT": 409,
    "SESSION_ENDED": 409,
    "PROTOCOL_DUPLICATE_COMMAND": 409,
    "AUTH_UNAUTHENTICATED": 401,
    "AUTH_INVALID_CREDENTIALS": 401,
    "AUTH_FORBIDDEN": 403,
    "AUTH_CSRF_FAILED": 403,
    "AUTH_IDENTIFIER_TAKEN": 409,
    "CONTENT_SCRIPT_NOT_FOUND": 404,
    "CONTENT_MATERIAL_NOT_FOUND": 404,
    "CONTENT_SCRIPT_NOT_EDITABLE": 409,
    "CONTENT_SCRIPT_NOT_READY": 409,
    "INTERNAL_ERROR": 500,
}


def error_response(exc: WJError) -> JSONResponse:
    from app.diagnostics.errors import envelope_for

    env = envelope_for(exc)
    status = _STATUS_BY_CODE.get(env.code, 400 if not env.retryable else 503)
    return JSONResponse(
        status_code=status,
        content={
            "error_id": str(env.error_id),
            "code": env.code,
            "domain": env.domain.value,
            "message": env.message,
            "retryable": env.retryable,
            "details": env.details,
        },
    )


__all__ = ["error_response"]
