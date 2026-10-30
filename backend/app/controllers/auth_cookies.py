"""账号 Cookie 约定（issue #17 / ADR-0002 §2）。

- `wenjing_session`：HttpOnly，承载原始会话 token。
- `wenjing_csrf`：可被 JS 读取，供 double-submit 校验。
- SameSite=Lax；生产（HTTPS）由 `WENJING_AUTH_COOKIE_SECURE=1` 打开 Secure。
"""

from __future__ import annotations

from fastapi import Response

SESSION_COOKIE = "wenjing_session"
CSRF_COOKIE = "wenjing_csrf"


def set_auth_cookies(
    response: Response,
    *,
    token: str,
    csrf_token: str,
    max_age: int,
    secure: bool,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        csrf_token,
        max_age=max_age,
        httponly=False,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_auth_cookies(response: Response, *, secure: bool) -> None:
    for name in (SESSION_COOKIE, CSRF_COOKIE):
        response.delete_cookie(name, path="/", samesite="lax", secure=secure)


__all__ = ["SESSION_COOKIE", "CSRF_COOKIE", "set_auth_cookies", "clear_auth_cookies"]
