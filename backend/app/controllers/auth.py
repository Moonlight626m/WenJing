"""账号 REST 路由（issue #17 / ADR-0002 §2）。

薄协议层：解析请求 → 委托 `AuthService` → 设置/清除 Cookie。
错误经全局 `WJError` 处理器统一为 envelope。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.auth import AuthSessionInfo, LoginRequest, RegisterRequest, UserPublic
from app.contracts.enums import UserRole
from app.controllers.auth_cookies import clear_auth_cookies, set_auth_cookies
from app.controllers.auth_deps import Principal, get_auth_service, get_principal, require_csrf
from app.infrastructure.config import get_settings
from app.infrastructure.db.session import get_session
from app.infrastructure.models.user import User
from app.services.auth import AuthService, IssuedSession, session_ttl

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        org_id=user.org_id,
        role=UserRole(user.role),
        email=user.email,
        phone=user.phone,
        nickname=user.nickname,
        created_at=user.created_at,
    )


def _apply_cookies(response: Response, issued: IssuedSession) -> None:
    settings = get_settings()
    set_auth_cookies(
        response,
        token=issued.token,
        csrf_token=issued.csrf_token,
        max_age=int(session_ttl().total_seconds()),
        secure=settings.auth_cookie_secure,
    )


@router.post("/register", status_code=201, response_model=AuthSessionInfo)
async def register(
    body: RegisterRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthSessionInfo:
    """注册并自动登录（返回用户 + CSRF token，会话 token 只走 HttpOnly Cookie）。"""
    issued = await service.register(
        session,
        email=body.email,
        phone=body.phone,
        password=body.password,
        nickname=body.nickname,
        ttl=session_ttl(),
    )
    _apply_cookies(response, issued)
    return AuthSessionInfo(user=_public(issued.user), csrf_token=issued.csrf_token)


@router.post("/login", response_model=AuthSessionInfo)
async def login(
    body: LoginRequest,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> AuthSessionInfo:
    issued = await service.login(
        session, identifier=body.identifier, password=body.password, ttl=session_ttl()
    )
    _apply_cookies(response, issued)
    return AuthSessionInfo(user=_public(issued.user), csrf_token=issued.csrf_token)


@router.post("/logout", status_code=204)
async def logout(
    response: Response,
    principal: Annotated[Principal, Depends(require_csrf)],
    session: Annotated[AsyncSession, Depends(get_session)],
    service: Annotated[AuthService, Depends(get_auth_service)],
) -> Response:
    """撤销服务端会话并清除 Cookie；需通过 CSRF 校验。

    撤销动作本身幂等（服务层不报错），但端点要求有效会话：已撤销/过期的会话
    在鉴权阶段即返回 401，因此重复调用返回 401 而非 204。
    """
    await service.logout(session, token=principal.token)
    clear_auth_cookies(response, secure=get_settings().auth_cookie_secure)
    response.status_code = 204
    return response


@router.get("/me", response_model=UserPublic)
async def me(principal: Annotated[Principal, Depends(get_principal)]) -> UserPublic:
    return _public(principal.user)


__all__ = ["router"]
