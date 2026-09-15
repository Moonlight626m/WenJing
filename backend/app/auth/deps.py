"""FastAPI 鉴权依赖（issue #17/#18 / ADR-0002 §2）。

- `get_principal`：从 Cookie 解析当前用户与服务端会话；命中滑动续期时重发 Cookie，
  保证浏览器 Cookie 的 max_age 与服务端 `expires_at` 同步滑动。
- `resolve_principal`：无 `Response` 的会话解析，供 WS 握手复用（Cookie 无法回写）。
- `require_csrf`：对状态变更方法做 double-submit 校验（header = cookie = 服务端存储）。
- `require_role`：RBAC 角色门（教师创作/发布端点等；#19 起接线）。
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Mapping
from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.access import Actor
from app.auth.cookies import CSRF_COOKIE, SESSION_COOKIE, set_auth_cookies
from app.auth.service import AuthService, session_ttl
from app.config import get_settings
from app.contracts.enums import UserRole
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

    @property
    def actor(self) -> Actor:
        """投影为领域身份，供应用层做资源归属/角色判定。"""
        return Actor(
            user_id=self.user.id,
            org_id=self.user.org_id,
            role=UserRole(self.user.role),
        )


async def resolve_principal(
    cookies: Mapping[str, str],
    session: AsyncSession,
) -> tuple[Principal, bool]:
    """从 Cookie 映射解析当前用户；返回 (principal, refreshed)。

    与 HTTP 无关：`get_principal` 与 WS 握手共用。无有效会话即 401。
    """
    token = cookies.get(SESSION_COOKIE)
    if not token:
        raise new(codes.AUTH_UNAUTHENTICATED)
    user, auth_session, refreshed = await get_auth_service().authenticate(
        session, token=token, ttl=session_ttl()
    )
    return (
        Principal(
            user=user,
            auth_session=auth_session,
            csrf_token=auth_session.csrf_token,
            token=token,
        ),
        refreshed,
    )


async def get_principal(
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> Principal:
    principal, refreshed = await resolve_principal(request.cookies, session)
    if refreshed:
        # 服务端续期成功，同步刷新 Cookie 的 max_age（生产 Secure 跟随配置）。
        set_auth_cookies(
            response,
            token=principal.token,
            csrf_token=principal.csrf_token,
            max_age=int(session_ttl().total_seconds()),
            secure=get_settings().auth_cookie_secure,
        )
    return principal


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


def require_role(
    *roles: UserRole,
) -> Callable[..., Coroutine[Any, Any, Principal]]:
    """RBAC 角色门：当前用户角色不在允许集合即 403（教师创作端点等）。"""
    allowed = frozenset(roles)

    async def _require_role(
        principal: Annotated[Principal, Depends(get_principal)],
    ) -> Principal:
        if principal.actor.role not in allowed:
            raise new(codes.AUTH_FORBIDDEN, extra={"reason": "insufficient role"})
        return principal

    return _require_role


__all__ = [
    "Principal",
    "get_auth_service",
    "get_principal",
    "require_csrf",
    "require_role",
    "resolve_principal",
]
