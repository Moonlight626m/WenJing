"""访问日志中间件（纯 ASGI）：API 层全量 req/resp 落日志。

分级约定：
- [info]  常规接口信息：method/path/query/状态码/延迟；
          `settings.log_body` 开启时附完整请求/响应 body（req、resp 各打一次，仅此层）。
- [error] 4xx（业务逻辑错误）与 5xx（系统错误）响应、未捕获异常。

业务层不再重复打印 body，只记关键信息（如模型响应全文，见 agents/llm_service.py）。
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

from app.infrastructure.diagnostics.logging import get_logger, redact_credentials

logger = get_logger("api.access")

# 前端高频轮询端点：日志降级为 debug（成功时），且不落 req/resp body。
# 命中规则：method 为 GET 且 path 匹配正则；失败（>=400）仍按常规分级记录。
_POLLING_PATH_RES = re.compile(r"^/api/scripts/[^/]+$")


def _is_polling(method: str, path: str) -> bool:
    return method == "GET" and _POLLING_PATH_RES.match(path) is not None


def _safe_body(chunks: list[bytes]) -> str | None:
    """拼接 body；JSON 时递归擦除凭据键（如登录密码）。解析失败原样保留。"""
    if not chunks:
        return None
    raw = b"".join(chunks).decode("utf-8", "replace")
    try:
        parsed = json.loads(raw)
    except ValueError:
        return raw
    try:
        return json.dumps(redact_credentials(parsed), ensure_ascii=False)
    except (TypeError, ValueError):
        return raw


class AccessLogMiddleware:
    """记录每个 HTTP 请求的完整 req/resp；WS 等非 http scope 直接透传。"""

    def __init__(self, app: Any, *, log_body: bool = True) -> None:
        self.app = app
        self._log_body = log_body

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")
        path = scope.get("path", "")
        query = scope.get("query_string", b"").decode("utf-8", "replace")

        req_chunks: list[bytes] = []

        async def buffering_receive() -> dict[str, Any]:
            message = await receive()
            if message.get("type") == "http.request":
                body = message.get("body") or b""
                if body:
                    req_chunks.append(body)
            return message

        status_holder = {"code": 0}
        resp_chunks: list[bytes] = []

        async def capture_send(message: dict[str, Any]) -> None:
            if message["type"] == "http.response.start":
                status_holder["code"] = message["status"]
            elif message["type"] == "http.response.body":
                body = message.get("body") or b""
                if body:
                    resp_chunks.append(body)
            await send(message)

        started = time.perf_counter()
        try:
            await self.app(scope, buffering_receive, capture_send)
        except Exception as exc:
            logger.error(
                "api_request_unhandled_exception",
                extra={
                    "wj_extra": {
                        "method": method,
                        "path": path,
                        "query": query,
                        "reason": f"{type(exc).__name__}: {exc}",
                    }
                },
            )
            raise
        duration_ms = round((time.perf_counter() - started) * 1000, 1)
        status = status_holder["code"]

        extra: dict[str, Any] = {
            "method": method,
            "path": path,
            "status": status,
            "duration_ms": duration_ms,
        }
        if query:
            extra["query"] = query
        polling = _is_polling(method, path)
        if self._log_body and not polling:
            # 注意：响应体整段缓冲（当前端点均为一次性 JSON，无流式端点）
            request_body = _safe_body(req_chunks)
            response_body = _safe_body(resp_chunks)
            if request_body is not None:
                extra["request_body"] = request_body
            if response_body is not None:
                extra["response_body"] = response_body

        if status >= 400:
            logger.error("api_request_failed", extra={"wj_extra": extra})
        elif polling:
            # 轮询期间每秒一次的成功请求：降级 debug，避免刷屏；需排查时开 debug 级别看。
            logger.debug("api_request_poll", extra={"wj_extra": extra})
        else:
            logger.info("api_request", extra={"wj_extra": extra})
