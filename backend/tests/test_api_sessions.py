"""会话 REST + WS 端到端集成测试（issue #5，真实 PG + fake adapters）。

覆盖验收：状态/命令 REST 流程；WS session_init 重建、命令提交、confirm/resync 补发；
错误 envelope（不存在会话 404）。
依赖真实 PostgreSQL；不可用时 skip。

注：#19 起剧本由教师创作 API（/api/materials、/api/scripts）生成并发布，
会话经 `script_id` 引用；本测试用 HTTP 生成剧本 + 应用层建可玩会话。
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401  # 确保 ORM 元数据注册
from app.contracts.enums import UserRole
from app.domain.access import Actor
from app.infrastructure.llm.fake import DeterministicAgentLLM
from app.main import create_app
from app.services.script_library import ScriptLibrary
from app.services.session_runtime import SessionApplication

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_MATERIAL_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)

_REGISTER = {
    "schema_version": "1.0.0",
    "email": "sessions.teacher@wenjing.local",
    "phone": None,
    "password": "supersecret1",
    "nickname": "会话教师",
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


def _execute(sql: str, **params) -> None:
    async def _run():
        engine = create_async_engine(
            _DB_URL, pool_timeout=5, connect_args={"timeout": 5}
        )
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    asyncio.run(_run())


@pytest.fixture(scope="module")
def client():
    if not asyncio.run(_db_available()):
        pytest.skip("PostgreSQL 未可用，跳过会话 API 集成测试")
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
            resp = c.post("/api/auth/register", json=_REGISTER)
            assert resp.status_code == 201, resp.text
            # 公开注册为 student；本测试需要教师权限，直接提权。
            _execute(
                "update users set role = 'teacher' where email = :e",
                e=_REGISTER["email"],
            )
            yield c
    finally:
        asyncio.run(_teardown())
        asyncio.run(engine.dispose())


def _csrf(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wenjing_csrf")}


async def _create_and_init_session(
    user_id: str, org_id: str, script_id: int
) -> str:
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        svc = SessionApplication(
            session_factory=factory, agent_llm=DeterministicAgentLLM()
        )
        actor = Actor(
            user_id=uuid.UUID(user_id),
            org_id=uuid.UUID(org_id),
            role=UserRole.TEACHER,
        )
        sid = (
            await svc.create_session(
                org_id=actor.org_id, owner_user_id=actor.user_id, script_id=script_id
            )
        ).session_id
        await svc.initialize_session(sid, actor)
        return str(sid)
    finally:
        await engine.dispose()


def _generate_direct(client: TestClient, script_id: int) -> None:
    """独立事件循环 await 生成（确定性 fake），避免 TestClient 后台任务竞态。"""
    me = client.get("/api/auth/me").json()

    async def _run() -> None:
        engine = create_async_engine(
            _DB_URL, pool_timeout=5, connect_args={"timeout": 5}
        )
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            actor = Actor(
                user_id=uuid.UUID(me["id"]),
                org_id=uuid.UUID(me["org_id"]),
                role=UserRole(me["role"]),
            )
            library = ScriptLibrary(session_factory=factory, script_llm=None)
            await library.start_generation(script_id, actor)
            await library.await_generation(script_id)
            assert (await library.progress(script_id)).status == "succeeded"
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _make_playable(client: TestClient) -> str:
    material = client.post(
        "/api/materials",
        json={
            "schema_version": "1.0.0",
            "source": "paste",
            "filename": None,
            "raw_text": _MATERIAL_TEXT,
        },
        headers=_csrf(client),
    )
    assert material.status_code == 201, material.text

    script = client.post(
        "/api/scripts",
        json={
            "schema_version": "1.0.0",
            "material_id": material.json()["id"],
            "name": "会话测试剧本",
            "description": None,
        },
        headers=_csrf(client),
    )
    assert script.status_code == 201, script.text
    script_id = script.json()["id"]

    _generate_direct(client, script_id)

    me = client.get("/api/auth/me").json()
    return asyncio.run(_create_and_init_session(me["id"], me["org_id"], script_id))


# ===== REST =====


def test_rest_full_flow(client):
    sid = _make_playable(client)

    status = client.get(f"/api/sessions/{sid}")
    assert status.status_code == 200
    assert status.json()["stage"] == "stage1_complete"

    body = client.get(f"/api/sessions/{sid}").json()
    role = body["playable_roles"][0]

    update = client.post(
        f"/api/sessions/{sid}/commands",
        json={
            "session_id": sid,
            "kind": "select_role",
            "payload": {"role_name": role},
        },
        headers=_csrf(client),
    )
    assert update.status_code == 200, update.text
    assert update.json()["state"]["stage"] == "stage2_reenacting"


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
    sid = _make_playable(client)
    body = client.get(f"/api/sessions/{sid}").json()
    return sid, body["playable_roles"][0]


def test_ws_init_command_and_resync(client):
    sid, role = _full_setup(client)
    base = f"/ws/{sid}"

    with client.websocket_connect(base) as ws:
        init = ws.receive_json()
        assert init["type"] == "session_init"
        assert init["payload"]["stage"] == "stage1_complete"
        assert "select_role" in init["payload"]["allowed_commands"]

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

    # 重连：session_init 从 DB 重建
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
