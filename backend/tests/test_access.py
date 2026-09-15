"""鉴权与资源隔离集成测试（issue #18 / ADR-0002 §3、§6）。

覆盖验收：
- 未登录访问业务端点 → 401 + envelope；
- 状态变更缺少 CSRF → 403 + envelope；
- 非 owner（含同 org / 跨 org）访问他人会话 → 403 + envelope；
- WS 无有效 Cookie → error(AUTH_UNAUTHENTICATED)，非 owner → error(AUTH_FORBIDDEN)；
- 角色门 `require_role` 允许/拒绝。

依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.auth.deps import Principal, require_role
from app.contracts.enums import UserRole
from app.errx import Error as WJError
from app.errx import codes
from app.main import create_app
from app.models.auth_session import AuthSession
from app.models.session import Session as SessionRecord
from app.models.user import User

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_REGISTER = {
    "schema_version": "1.0.0",
    "phone": None,
    "password": "supersecret1",
}


def _engine():
    return create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})


async def _db_available() -> bool:
    engine = _engine()
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


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
        pytest.skip("PostgreSQL 未可用，跳过鉴权集成测试")

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
    from app.db import session as db_session

    asyncio.run(db_session.engine.dispose())
    app = create_app()
    with TestClient(app) as c:
        yield c
    asyncio.run(db_session.engine.dispose())


@pytest.fixture(autouse=True)
def _fresh(client):
    """每个用例前清空全部业务/账号数据，避免跨用例串扰（FK 需 CASCADE）。"""
    _execute(
        "truncate table commands, snapshots, events, event_branches, sessions, "
        "materials, scripts, auth_sessions, users, orgs restart identity cascade"
    )
    client.cookies.clear()
    yield


def _register(client: TestClient, email: str, nickname: str = "用户") -> dict:
    resp = client.post(
        "/api/auth/register", json={**_REGISTER, "email": email, "nickname": nickname}
    )
    assert resp.status_code == 201, resp.text
    me = client.get("/api/auth/me").json()
    return {
        "session": client.cookies.get("wenjing_session"),
        "csrf": client.cookies.get("wenjing_csrf"),
        "me": me,
    }


def _act_as(client: TestClient, account: dict) -> None:
    client.cookies.clear()
    client.cookies.set("wenjing_session", account["session"])
    client.cookies.set("wenjing_csrf", account["csrf"])


def _csrf(account: dict) -> dict[str, str]:
    return {"X-CSRF-Token": account["csrf"]}


def _create_owned_session(owner: dict) -> str:
    async def _run() -> str:
        engine = _engine()
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        sid = uuid.uuid4()
        try:
            async with factory() as s:
                s.add(
                    SessionRecord(
                        id=sid,
                        org_id=uuid.UUID(owner["me"]["org_id"]),
                        owner_user_id=uuid.UUID(owner["me"]["id"]),
                    )
                )
                await s.commit()
        finally:
            await engine.dispose()
        return str(sid)

    return asyncio.run(_run())


def _move_to_new_org(email: str) -> None:
    """把账号迁到独立 org，模拟跨 org 用户。"""

    async def _run() -> None:
        engine = _engine()
        try:
            async with engine.begin() as conn:
                oid = uuid.uuid4()
                await conn.execute(
                    text(
                        "insert into orgs (id, name, created_at) "
                        "values (:id, :name, now())"
                    ),
                    {"id": oid, "name": f"isolated-{oid}"},
                )
                await conn.execute(
                    text("update users set org_id = :oid where email = :email"),
                    {"oid": oid, "email": email},
                )
        finally:
            await engine.dispose()

    asyncio.run(_run())


# ===== REST 鉴权 =====


def test_business_endpoint_requires_login(client):
    client.cookies.clear()
    resp = client.get("/api/sessions/00000000-0000-0000-0000-000000000001")
    assert resp.status_code == 401
    assert resp.json()["code"] == "AUTH_UNAUTHENTICATED"
    assert resp.json()["domain"] == "auth"

    r2 = client.post(
        "/api/sessions/00000000-0000-0000-0000-000000000001/commands",
        json={"session_id": "00000000-0000-0000-0000-000000000001", "kind": "exit_game"},
    )
    assert r2.status_code == 401
    assert r2.json()["code"] == "AUTH_UNAUTHENTICATED"


def test_mutating_endpoint_requires_csrf(client):
    owner = _register(client, "csrf@wenjing.local")
    sid = _create_owned_session(owner)
    _act_as(client, owner)

    missing = client.post(
        f"/api/sessions/{sid}/material",
        json={"source": "paste", "raw_text": "从前有座山。"},
    )
    assert missing.status_code == 403
    assert missing.json()["code"] == "AUTH_CSRF_FAILED"

    bad = client.post(
        f"/api/sessions/{sid}/material",
        json={"source": "paste", "raw_text": "从前有座山。"},
        headers={"X-CSRF-Token": "wrong"},
    )
    assert bad.status_code == 403
    assert bad.json()["code"] == "AUTH_CSRF_FAILED"


def test_owner_can_access_own_session(client):
    owner = _register(client, "owner@wenjing.local")
    sid = _create_owned_session(owner)
    _act_as(client, owner)
    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 200
    assert resp.json()["stage"] == "init"


def test_other_user_in_same_org_denied(client):
    owner = _register(client, "owner2@wenjing.local", "拥有者")
    sid = _create_owned_session(owner)
    other = _register(client, "other@wenjing.local", "同校同学")

    _act_as(client, other)
    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 403
    assert resp.json()["code"] == "AUTH_FORBIDDEN"

    denied = client.post(
        f"/api/sessions/{sid}/material",
        json={"source": "paste", "raw_text": "从前有座山。"},
        headers=_csrf(other),
    )
    assert denied.status_code == 403
    assert denied.json()["code"] == "AUTH_FORBIDDEN"


def test_cross_org_user_denied(client):
    owner = _register(client, "owner3@wenjing.local", "拥有者")
    sid = _create_owned_session(owner)
    outsider = _register(client, "outsider@wenjing.local", "外校同学")
    _move_to_new_org("outsider@wenjing.local")

    _act_as(client, outsider)
    resp = client.get(f"/api/sessions/{sid}")
    assert resp.status_code == 403
    assert resp.json()["code"] == "AUTH_FORBIDDEN"


# ===== WS 鉴权 =====


def test_ws_requires_cookie(client):
    owner = _register(client, "ws1@wenjing.local")
    sid = _create_owned_session(owner)
    client.cookies.clear()
    with client.websocket_connect(f"/ws/{sid}") as ws:
        err = ws.receive_json()
    assert err["type"] == "error"
    assert err["payload"]["code"] == "AUTH_UNAUTHENTICATED"


def test_ws_rejects_non_owner(client):
    owner = _register(client, "ws2@wenjing.local", "拥有者")
    sid = _create_owned_session(owner)
    other = _register(client, "ws3@wenjing.local", "其他")
    _act_as(client, other)
    with client.websocket_connect(f"/ws/{sid}") as ws:
        err = ws.receive_json()
    assert err["type"] == "error"
    assert err["payload"]["code"] == "AUTH_FORBIDDEN"


def test_ws_rejects_cross_org(client):
    owner = _register(client, "ws4@wenjing.local", "拥有者")
    sid = _create_owned_session(owner)
    outsider = _register(client, "ws5@wenjing.local", "外校")
    _move_to_new_org("ws5@wenjing.local")
    _act_as(client, outsider)
    with client.websocket_connect(f"/ws/{sid}") as ws:
        err = ws.receive_json()
    assert err["type"] == "error"
    assert err["payload"]["code"] == "AUTH_FORBIDDEN"


# ===== 角色门 =====


def _principal(role: str) -> Principal:
    return Principal(
        user=User(
            org_id=uuid.uuid4(),
            role=role,
            email=f"{role}@wenjing.local",
            nickname=role,
            password_hash="unused",
        ),
        auth_session=AuthSession(
            user_id=uuid.uuid4(), token_hash="h", csrf_token="c"
        ),
        csrf_token="c",
        token="t",
    )


def test_require_role_allows_and_denies():
    dep = require_role(UserRole.TEACHER)

    asyncio.run(dep(_principal("teacher")))

    with pytest.raises(WJError) as excinfo:
        asyncio.run(dep(_principal("student")))
    assert excinfo.value.code == codes.AUTH_FORBIDDEN

    # super_admin 不自动获得 teacher 权限（无层级包含）
    with pytest.raises(WJError):
        asyncio.run(dep(_principal("super_admin")))
