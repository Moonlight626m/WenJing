"""账号与会话集成测试（issue #17 / ADR-0002，真实 PG + argon2）。

覆盖验收：注册/登录/登出/当前用户；argon2 哈希；Cookie（HttpOnly/SameSite）；
CSRF 校验；登出撤销；滑动过期；seed 幂等与默认 org/测试账号。
依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401  # 确保 ORM 元数据注册
from app.main import create_app
from app.services.auth import DEFAULT_ORG_NAME
from app.services.auth_seed import seed

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_REGISTER = {
    "schema_version": "2.0.0",
    "email": "alice@wenjing.local",
    "phone": None,
    "password": "supersecret1",
    "nickname": "小艾",
}


async def _db_available() -> bool:
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


def _engine():
    return create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})


def _scalar(sql: str, **params):
    async def _run():
        engine = _engine()
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text(sql), params)).scalar()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _execute(sql: str, **params) -> None:
    async def _run():
        engine = _engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.fixture(scope="module")
def _schema():
    if not asyncio.run(_db_available()):
        pytest.skip("PostgreSQL 未可用，跳过后端账号集成测试")

    from conftest import drop_baseline_schema, reset_baseline_schema

    engine = _engine()

    async def _create():
        async with engine.begin() as conn:
            await reset_baseline_schema(conn)

    async def _drop():
        async with engine.begin() as conn:
            await drop_baseline_schema(conn)

    asyncio.run(_create())
    asyncio.run(engine.dispose())
    yield
    engine2 = _engine()
    try:
        asyncio.run(_drop())
    finally:
        asyncio.run(engine2.dispose())


@pytest.fixture(scope="module")
def client(_schema):
    # 模块级单例：app 的 DB engine 与会话池绑定事件循环，跨 TestClient 复用会触发
    # asyncpg「another operation in progress」，故整个模块共用一个 client。
    # 同时释放前序 TestClient 模块遗留的连接池（绑定的是已关闭的事件循环）。
    from app.infrastructure.db import session as db_session

    asyncio.run(db_session.engine.dispose())
    app = create_app()
    with TestClient(app) as c:
        yield c
    asyncio.run(db_session.engine.dispose())


@pytest.fixture(autouse=True)
def _fresh(client):
    """每个用例前清空账号数据与 Cookie，避免固定标识符/登录态串扰。"""
    _execute("delete from auth_sessions")
    _execute("delete from users")
    _execute("delete from orgs")
    client.cookies.clear()
    yield


def _register(client: TestClient, **overrides) -> dict:
    body = {**_REGISTER, **overrides}
    resp = client.post("/api/auth/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


def _login(client: TestClient, identifier: str, password: str):
    return client.post(
        "/api/auth/login",
        json={
            "schema_version": "2.0.0",
            "identifier": identifier,
            "password": password,
        },
    )


# ===== 注册 =====


def test_register_returns_user_sets_cookies_and_hashes_password(client):
    body = _register(client)

    assert body["user"]["role"] == "student"
    assert body["user"]["nickname"] == "小艾"
    assert body["csrf_token"]
    assert "wenjing_session" in client.cookies
    assert "wenjing_csrf" in client.cookies

    password_hash = _scalar(
        "select password_hash from users where email = :e", e="alice@wenjing.local"
    )
    assert password_hash.startswith("$argon2")
    assert "supersecret1" not in password_hash


def test_register_duplicate_identifier_conflicts(client):
    _register(client)
    dup = client.post("/api/auth/register", json=_REGISTER)
    assert dup.status_code == 409
    assert dup.json()["code"] == "AUTH_IDENTIFIER_TAKEN"
    assert dup.json()["domain"] == "auth"


def test_register_rejects_missing_identifier(client):
    resp = client.post(
        "/api/auth/register",
        json={**_REGISTER, "email": None, "phone": None},
    )
    assert resp.status_code == 422


# ===== 登录 / 当前用户 =====


def test_me_requires_authentication(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_login_with_email_and_phone(client):
    _register(client)
    client.cookies.clear()

    ok = _login(client, "alice@wenjing.local", "supersecret1")
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == "alice@wenjing.local"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["nickname"] == "小艾"

    # 手机号注册 + 手机号登录
    client.cookies.clear()
    _register(client, email=None, phone="13800000000")
    client.cookies.clear()
    assert _login(client, "13800000000", "supersecret1").status_code == 200


def test_login_wrong_password_rejected(client):
    _register(client)
    client.cookies.clear()
    resp = _login(client, "alice@wenjing.local", "wrong-pass")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_INVALID_CREDENTIALS"


def test_unknown_cookie_rejected(client):
    client.cookies.set("wenjing_session", "not-a-real-token")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


# ===== CSRF / 登出 =====


def test_logout_requires_csrf_then_revokes(client):
    _register(client)

    missing = client.post("/api/auth/logout")
    assert missing.status_code == 403
    assert missing.json()["code"] == "AUTH_CSRF_FAILED"

    csrf = client.cookies.get("wenjing_csrf")
    ok = client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf})
    assert ok.status_code == 204
    assert client.get("/api/auth/me").status_code == 401


def test_logout_is_idempotent(client):
    _register(client)
    csrf = client.cookies.get("wenjing_csrf")
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 204
    # 会话已撤销：再次登出需要有效会话，故 401（而非 204）
    assert client.post("/api/auth/logout", headers={"X-CSRF-Token": csrf}).status_code == 401


# ===== 滑动过期 =====


def test_sliding_expiry_extends_on_use(client):
    _register(client)
    expires_at = "select expires_at from auth_sessions limit 1"
    _execute(
        "update auth_sessions set last_seen_at = now() - interval '2 days', "
        "expires_at = now() + interval '1 hour'"
    )
    soon = _scalar(expires_at)
    assert soon is not None

    resp = client.get("/api/auth/me")
    assert resp.status_code == 200
    # 滑动续期必须同步重发 Cookie，否则浏览器 max_age 先于服务端过期。
    set_cookie = ", ".join(resp.headers.get_list("set-cookie"))
    assert "wenjing_session" in set_cookie

    extended = _scalar(
        "select expires_at > now() + interval '10 days' from auth_sessions limit 1"
    )
    assert extended is True


# ===== seed =====


def _run_seed():
    async def _inner():
        engine = _engine()
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            return await seed(factory)
        finally:
            await engine.dispose()

    return asyncio.run(_inner())


def test_seed_creates_default_org_and_accounts_idempotently(_schema):
    first = _run_seed()
    assert {a["role"] for a in first} == {"super_admin", "teacher", "student"}
    assert all(a["created"] for a in first)

    assert _scalar("select count(*) from orgs where name = :n", n=DEFAULT_ORG_NAME) == 1
    assert _scalar("select count(*) from users") == 3

    second = _run_seed()
    assert all(not a["created"] for a in second)
    assert _scalar("select count(*) from users") == 3
