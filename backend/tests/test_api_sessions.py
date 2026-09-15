"""会话 REST + WS 端到端集成测试（issue #5，真实 PG + fake adapters）。

覆盖验收：状态/导入/生成 REST 流程；WS session_init 重建、命令提交、
confirm/resync 补发；错误 envelope（不存在会话 404）。
依赖真实 PostgreSQL；不可用时 skip。

注（issue #17）：匿名 `POST /api/sessions` 入口已随 ADR-0002 移除，本测试改为
在应用层/DB 直接建 session（新入口由 #21 的学生游玩 API 提供）。
注（issue #18）：业务端点要求登录 + 状态变更 CSRF；WS 握手校验会话 Cookie。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401  # 确保 ORM 元数据注册
from app.main import create_app
from app.models.session import Session as SessionRecord

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_MATERIAL_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)

_REGISTER = {
    "schema_version": "1.0.0",
    "email": "sessions@wenjing.local",
    "phone": None,
    "password": "supersecret1",
    "nickname": "会话测试",
}


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


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


@pytest.fixture(scope="module")
def client():
    if not asyncio.run(_db_available()):
        pytest.skip("PostgreSQL 未可用，跳过会话 API 集成测试")
    # PG 可用：清场（迁移测试可能残留），再建表
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})

    from conftest import drop_baseline_schema, reset_baseline_schema

    async def _reset():
        async with engine.begin() as conn:
            await reset_baseline_schema(conn)

    async def _teardown():
        async with engine.begin() as conn:
            await drop_baseline_schema(conn)

    asyncio.run(_reset())
    asyncio.run(engine.dispose())
    app = create_app()
    try:
        with TestClient(app) as c:
            # 业务端点要求登录（#18）：注册拥有者并保持 Cookie。
            resp = c.post("/api/auth/register", json=_REGISTER)
            assert resp.status_code == 201, resp.text
            yield c
    finally:
        asyncio.run(_teardown())
        asyncio.run(engine.dispose())


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wenjing_csrf")}


def _material_body() -> dict:
    return {"source": "paste", "raw_text": _MATERIAL_TEXT}


def _scalar(sql: str, **params):
    async def _run():
        engine = create_async_engine(
            _DB_URL, pool_timeout=5, connect_args={"timeout": 5}
        )
        try:
            async with engine.connect() as conn:
                return (await conn.execute(text(sql), params)).scalar()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


async def _insert_session(owner_user_id: str, org_id: str) -> str:
    """应用层建 session：匿名入口移除后，测试直接写 sessions 表（带归属）。"""
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    sid = uuid.uuid4()
    try:
        async with factory() as s:
            s.add(
                SessionRecord(
                    id=sid,
                    org_id=uuid.UUID(org_id),
                    owner_user_id=uuid.UUID(owner_user_id),
                )
            )
            await s.commit()
    finally:
        await engine.dispose()
    return str(sid)


def _create_session(client: TestClient) -> str:
    me = client.get("/api/auth/me").json()
    return asyncio.run(_insert_session(me["id"], me["org_id"]))


# ===== REST =====


def test_rest_full_flow(client):
    sid = _create_session(client)

    status = client.get(f"/api/sessions/{sid}")
    assert status.status_code == 200
    assert status.json()["stage"] == "init"

    analysis = client.post(
        f"/api/sessions/{sid}/material", json=_material_body(), headers=_csrf(client)
    )
    assert analysis.status_code == 200
    assert analysis.json()["characters"], "叙事样例应提取出人物"

    pkg = client.post(f"/api/sessions/{sid}/generate", headers=_csrf(client))
    assert pkg.status_code == 200, pkg.text
    body = pkg.json()
    assert body["characters"] and body["scenes"]
    assert body["playable_roles"]

    status = client.get(f"/api/sessions/{sid}")
    assert status.json()["stage"] == "stage1_complete"
    assert status.json()["generation"]["status"] == "succeeded"

    # 归属写入（#18）：materials/scripts/sessions 均带上创建者的 owner/org。
    me = client.get("/api/auth/me").json()
    assert (
        _scalar("select owner_user_id::text from materials order by id desc limit 1")
        == me["id"]
    )
    assert (
        _scalar("select owner_user_id::text from scripts order by id desc limit 1")
        == me["id"]
    )
    assert (
        _scalar(
            "select org_id::text from sessions where id = :sid", sid=uuid.UUID(sid)
        )
        == me["org_id"]
    )


def test_rest_error_envelopes(client):
    ghost = "00000000-0000-0000-0000-000000000001"
    resp = client.get(f"/api/sessions/{ghost}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "SESSION_NOT_FOUND"
    assert body["domain"] == "session"
    assert "error_id" in body

    bad = client.get("/api/sessions/not-a-uuid")
    assert bad.status_code in (400, 404)
    assert bad.json()["code"].startswith("PROTOCOL_") or "code" in bad.json()


# ===== WS =====


def _full_setup(client) -> tuple[str, str]:
    sid = _create_session(client)
    client.post(
        f"/api/sessions/{sid}/material", json=_material_body(), headers=_csrf(client)
    )
    pkg = client.post(f"/api/sessions/{sid}/generate", headers=_csrf(client)).json()
    role = pkg["playable_roles"][0]
    return sid, role


def test_ws_init_command_and_resync(client):
    sid, role = _full_setup(client)
    base = f"/ws/{sid}"

    with client.websocket_connect(base) as ws:
        init = ws.receive_json()
        assert init["type"] == "session_init"
        assert init["payload"]["stage"] == "stage1_complete"
        assert "select_role" in init["payload"]["allowed_commands"]

        # 提交选角命令（协议冻结的 submit_command 形状）
        ws.send_json(
            {
                "type": "submit_command",
                "command": {
                    "session_id": sid,
                    "kind": "select_role",
                    "payload": {"role_name": role},
                },
            }
        )
        msgs = []
        while True:
            msg = ws.receive_json()
            msgs.append(msg)
            if msg["type"] == "interaction":
                break
        types = [m["type"] for m in msgs]
        assert "system" in types  # 选角确认 + 阶段切换
        assert "narrative" in types
        assert msgs[-1]["type"] == "interaction"
        seqs = [m["seq"] for m in msgs]
        assert seqs == sorted(seqs), "seq 必须随事件序单调"

        last_confirmed = seqs[-2]  # 交互点前最后一条
        ws.send_json({"type": "confirm_messages", "last_confirmed_seq": last_confirmed})
        ws.send_json({"type": "resync_request", "last_confirmed_seq": last_confirmed})
        replayed = ws.receive_json()
        assert replayed["type"] == "interaction"  # 补发缺口（交互点）

    # 重连：session_init 从 DB 重建（进程内 runtime 已存在，也应一致）
    with client.websocket_connect(base) as ws:
        init = ws.receive_json()
        assert init["payload"]["stage"] == "stage2_reenacting"
        assert init["payload"]["player_role"] == role


def test_ws_rejects_unknown_session(client):
    ghost = "00000000-0000-0000-0000-000000000099"
    with client.websocket_connect(f"/ws/{ghost}") as ws:
        err = ws.receive_json()
    assert err["type"] == "error"
    assert err["payload"]["code"] == "SESSION_NOT_FOUND"


def test_ws_rejects_malformed_message(client):
    sid, role = _full_setup(client)
    with client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()  # session_init
        ws.send_json({"type": "bogus"})
        err = ws.receive_json()
        assert err["type"] == "error"
        assert err["payload"]["code"] in (
            "PROTOCOL_MALFORMED_MESSAGE",
            "PROTOCOL_UNKNOWN_COMMAND",
        )
