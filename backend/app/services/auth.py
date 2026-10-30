"""账号应用服务（issue #17 / ADR-0002 §1–2）。

职责：
- 注册（默认 `student`）、登录、登出、会话解析（14 天滑动过期）。
- 服务端可撤销会话：Cookie 只带原始 token，库中存 SHA-256 哈希。
- CSRF token 随会话签发，供 double-submit 校验。

不负责 HTTP/cookie 序列化（见 `app/controllers/auth.py`）。
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.enums import UserRole
from app.infrastructure.config import get_settings
from app.infrastructure.errx import codes, new
from app.infrastructure.models.auth_session import AuthSession
from app.infrastructure.models.org import Org
from app.infrastructure.models.user import User
from app.services.auth_passwords import hash_password, needs_rehash, verify_password

DEFAULT_ORG_NAME = "文境演示学校"
# 滑动过期刷新节流：每次请求都写库没必要，超过该间隔才续期
_REFRESH_AFTER = timedelta(hours=1)


@dataclass(frozen=True)
class IssuedSession:
    """一次签发：用户 + 原始会话 token + CSRF token（均已可用）。"""

    user: User
    token: str
    csrf_token: str


def session_ttl() -> timedelta:
    """会话有效期（滑动过期窗口），由配置 `auth_session_ttl_days` 决定。"""
    return timedelta(days=get_settings().auth_session_ttl_days)


def _norm_email(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip().lower() or None


def _norm_phone(value: str | None) -> str | None:
    if not value:
        return None
    return value.strip() or None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AuthService:
    """账号与会话的唯一业务入口。

    无状态：每个方法显式接收 `AsyncSession`，由调用方（REST 依赖 / seed）管理事务边界。
    """

    # ===== 默认组织 =====

    async def default_org(self, session: AsyncSession) -> Org:
        """取默认组织；不存在则创建（MVP 单组织）。"""
        org = (
            await session.execute(select(Org).where(Org.name == DEFAULT_ORG_NAME))
        ).scalar_one_or_none()
        if org is None:
            org = Org(name=DEFAULT_ORG_NAME)
            session.add(org)
            await session.flush()
        return org

    # ===== 注册 / 登录 =====

    async def create_user(
        self,
        session: AsyncSession,
        *,
        email: str | None,
        phone: str | None,
        password: str,
        nickname: str,
        role: UserRole = UserRole.STUDENT,
    ) -> User:
        """创建账号（不签发登录会话）；标识重复时抛 AUTH_IDENTIFIER_TAKEN。"""
        email = _norm_email(email)
        phone = _norm_phone(phone)
        if email is not None and await self._identifier_exists(session, email=email):
            raise new(codes.AUTH_IDENTIFIER_TAKEN, extra={"identifier": email})
        if phone is not None and await self._identifier_exists(session, phone=phone):
            raise new(codes.AUTH_IDENTIFIER_TAKEN, extra={"identifier": phone})

        org = await self.default_org(session)
        user = User(
            org_id=org.id,
            role=role.value,
            email=email,
            phone=phone,
            nickname=nickname.strip(),
            password_hash=hash_password(password),
        )
        session.add(user)
        try:
            await session.flush()
        except IntegrityError as exc:
            await session.rollback()
            raise new(
                codes.AUTH_IDENTIFIER_TAKEN, extra={"identifier": email or phone or ""}
            ) from exc
        return user

    async def register(
        self,
        session: AsyncSession,
        *,
        email: str | None,
        phone: str | None,
        password: str,
        nickname: str,
        role: UserRole = UserRole.STUDENT,
        ttl: timedelta,
    ) -> IssuedSession:
        """注册并直接签发会话（自动登录）。"""
        user = await self.create_user(
            session,
            email=email,
            phone=phone,
            password=password,
            nickname=nickname,
            role=role,
        )
        issued = self._issue(session, user, ttl)
        await session.commit()
        return issued

    async def login(
        self,
        session: AsyncSession,
        *,
        identifier: str,
        password: str,
        ttl: timedelta,
    ) -> IssuedSession:
        user = await self.find_by_identifier(session, identifier)
        if user is None or not verify_password(user.password_hash, password):
            raise new(codes.AUTH_INVALID_CREDENTIALS, extra={"identifier": identifier})
        if needs_rehash(user.password_hash):
            user.password_hash = hash_password(password)
        issued = self._issue(session, user, ttl)
        await session.commit()
        return issued

    # ===== 会话解析 / 登出 =====

    async def authenticate(
        self, session: AsyncSession, *, token: str, ttl: timedelta
    ) -> tuple[User, AuthSession, bool]:
        """校验 Cookie token，返回 (user, auth_session, refreshed)。

        无效/过期/撤销即 401；`refreshed=True` 表示本次触发了滑动续期，
        调用方需重发 Cookie（否则浏览器 max_age 不会随服务端一起滑动）。
        """
        now = datetime.now(UTC)
        row = (
            await session.execute(
                select(AuthSession).where(AuthSession.token_hash == _hash_token(token))
            )
        ).scalar_one_or_none()
        if (
            row is None
            or row.revoked_at is not None
            or row.expires_at <= now
        ):
            raise new(codes.AUTH_UNAUTHENTICATED)
        user = await session.get(User, row.user_id)
        if user is None:
            raise new(codes.AUTH_UNAUTHENTICATED)
        refreshed = now - row.last_seen_at >= _REFRESH_AFTER
        if refreshed:
            row.last_seen_at = now
            row.expires_at = now + ttl
            await session.commit()
        return user, row, refreshed

    async def logout(self, session: AsyncSession, *, token: str) -> None:
        """撤销服务端会话；幂等（未知/已撤销 token 不报错）。"""
        row = (
            await session.execute(
                select(AuthSession).where(AuthSession.token_hash == _hash_token(token))
            )
        ).scalar_one_or_none()
        if row is not None and row.revoked_at is None:
            row.revoked_at = datetime.now(UTC)
            await session.commit()

    # ===== 内部工具 =====

    def _issue(
        self, session: AsyncSession, user: User, ttl: timedelta
    ) -> IssuedSession:
        now = datetime.now(UTC)
        token = secrets.token_urlsafe(32)
        csrf = secrets.token_urlsafe(24)
        session.add(
            AuthSession(
                user_id=user.id,
                token_hash=_hash_token(token),
                csrf_token=csrf,
                last_seen_at=now,
                expires_at=now + ttl,
            )
        )
        return IssuedSession(user=user, token=token, csrf_token=csrf)

    @staticmethod
    async def _identifier_exists(
        session: AsyncSession, *, email: str | None = None, phone: str | None = None
    ) -> bool:
        stmt = select(User.id)
        if email is not None:
            stmt = stmt.where(User.email == email)
        if phone is not None:
            stmt = stmt.where(User.phone == phone)
        return (await session.execute(stmt.limit(1))).scalar_one_or_none() is not None

    @staticmethod
    async def find_by_identifier(session: AsyncSession, identifier: str) -> User | None:
        identifier = identifier.strip()
        lookup = identifier.lower()
        stmt = select(User).where(
            (User.email == lookup) | (User.phone == identifier)
        )
        return (await session.execute(stmt.limit(1))).scalar_one_or_none()


__all__ = ["AuthService", "IssuedSession", "DEFAULT_ORG_NAME", "session_ttl"]
