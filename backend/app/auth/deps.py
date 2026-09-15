"""FastAPI 鉴权依赖（issue #17 / ADR-0002 §2）。

- `get_principal`：从 Cookie 解析当前用户与服务端会话；命中滑动续期时重发 Cookie，
  保证浏览器 Cookie 的 max_age 与服务端 `expires_at` 同步滑动。
- `require_csrf`：对状态变更方法做 double-submit 校验（header = cookie = 服务端存储）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.cookies import CSRF_COOKIE, SESSION_COOKIE, set_auth_cookies
from app.auth.service import AuthService, session_ttl
from app.config import get_settings
from app.db.session import get_session
from app.errx import codes, new
from app.models.auth_session import AuthSession
from app.models.user import User

_MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

_auth_service: AuthService | None = None


def get_auth_service() -> AuthService:
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service


@dataclass
class Principal:
    """一次请求的鉴权上下文。"""

    user: User
    auth_session: AuthSession
    csrf_token: str
    token: str


async def get_principal(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise new(codes.AUTH_UNAUTHENTICATED)
    ttl = session_ttl()
    user, auth_session, refreshed = await get_auth_service().authenticate(
        session, token=token, ttl=ttl
    )
    if refreshed:
        # 服务端续期成功，同步刷新 Cookie 的 max_age（生产 Secure 跟随配置）。
        set_auth_cookies(
            response,
            token=token,
            csrf_token=auth_session.csrf_token,
            max_age=int(ttl.total_seconds()),
            secure=get_settings().auth_cookie_secure,
        )
    return Principal(
        user=user, auth_session=auth_session, csrf_token=auth_session.csrf_token, token=token
    )


async def require_csrf(
    request: Request,
    principal: Annotated[Principal, Depends(get_principal)],
) -> Principal:
    """状态变更方法必须通过 double-submit 校验。"""
    if request.method not in _MUTATING_METHODS:
        return principal
    header = request.headers.get(get_settings().auth_csrf_header)
    cookie = request.cookies.get(CSRF_COOKIE)
    if not header or not cookie or header != cookie or header != principal.csrf_token:
        raise new(codes.AUTH_CSRF_FAILED)
    return principal


__all__ = [
    "Principal",
    "get_auth_service",
    "get_principal",
    "require_csrf",
]
