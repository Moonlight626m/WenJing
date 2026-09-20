"""学生游玩 API 集成测试（issue #21 / ADR-0002 §3）。

覆盖验收：
- 剧本广场：已发布且可见的剧本（同 org + public）；草稿/不可见不进广场；
- 学生可从可见剧本开局、选角、游玩至 Stage3 / 终局；
- 「我的游戏」列表与续玩；刷新后从 DB 恢复一致（无状态命令路径）；
- 教师可游玩自己的剧本（含未发布草稿）；
- 未登录 / 缺 CSRF / 不可见剧本 / 未生成剧本 的拒绝语义。

依赖真实 PostgreSQL；不可用时 skip。
"""

from __future__ import annotations

import asyncio
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.contracts.enums import UserRole
from app.main import create_app

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_MATERIAL_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
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


def _move_to_new_org(email: str) -> None:
    """把账号迁到独立 org，模拟跨 org 用户。"""

    async def _run() -> None:
        import uuid as _uuid

        engine = _engine()
        try:
            async with engine.begin() as conn:
                oid = _uuid.uuid4()
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


@pytest.fixture(scope="module")
def client():
    if not asyncio.run(_db_available()):
        pytest.skip("PostgreSQL 未可用，跳过学生游玩 API 集成测试")
    engine = _engine()

    from conftest import drop_baseline_schema, reset_baseline_schema

    async def _reset():
        async with engine.begin() as conn:
            await reset_baseline_schema(conn)

    async def _teardown():
        async with engine.begin() as conn:
            await drop_baseline_schema(conn)

    asyncio.run(_reset())
    asyncio.run(engine.dispose())

    # 测试必须走确定性 fake（backend/.env 可能配置了真实 LLM key）
    from app.agents.fake_llm import DeterministicAgentLLM
    from app.api import routes as routes_mod
    from app.db.session import SessionLocal
    from app.session.application import SessionApplication

    original = routes_mod._application
    routes_mod._application = SessionApplication(
        session_factory=SessionLocal, agent_llm=DeterministicAgentLLM()
    )

    app = create_app()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        routes_mod._application = original
        asyncio.run(_teardown())
        asyncio.run(engine.dispose())


def _register(client: TestClient, email: str, nickname: str = "用户", *, role: str) -> dict:
    client.cookies.clear()
    resp = client.post(
        "/api/auth/register", json={**_REGISTER, "email": email, "nickname": nickname}
    )
    assert resp.status_code == 201, resp.text
    if role != UserRole.STUDENT.value:
        _execute("update users set role = :r where email = :e", r=role, e=email)
    me = client.get("/api/auth/me").json()
    assert me["role"] == role
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


def _generate_direct(account: dict, script_id: int) -> None:
    """独立事件循环 await 生成（确定性合成），避免 TestClient 后台任务竞态。"""

    async def _run() -> None:
        import uuid as _uuid

        from app.access import Actor
        from app.scripts.service import ScriptLibrary

        engine = _engine()
        factory = async_sessionmaker(
            engine, class_=AsyncSession, expire_on_commit=False
        )
        try:
            actor = Actor(
                user_id=_uuid.UUID(account["me"]["id"]),
                org_id=_uuid.UUID(account["me"]["org_id"]),
                role=UserRole(account["me"]["role"]),
            )
            library = ScriptLibrary(session_factory=factory, script_llm=None)
            await library.start_generation(script_id, actor)
            await library.await_generation(script_id)
            assert (await library.progress(script_id)).status == "succeeded"
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _make_script(
    client: TestClient, account: dict, *, name: str, generate: bool = True
) -> int:
    _act_as(client, account)
    material = client.post(
        "/api/materials",
        json={
            "schema_version": "1.0.0",
            "source": "paste",
            "filename": None,
            "raw_text": _MATERIAL_TEXT,
        },
        headers=_csrf(account),
    )
    assert material.status_code == 201, material.text
    script = client.post(
        "/api/scripts",
        json={
            "schema_version": "1.0.0",
            "material_id": material.json()["id"],
            "name": name,
            "description": None,
        },
        headers=_csrf(account),
    )
    assert script.status_code == 201, script.text
    script_id = script.json()["id"]
    if generate:
        _generate_direct(account, script_id)
    return script_id


def _publish(client: TestClient, account: dict, script_id: int, visibility: str) -> None:
    _act_as(client, account)
    resp = client.post(
        f"/api/scripts/{script_id}/publish",
        json={"schema_version": "1.0.0", "visibility": visibility},
        headers=_csrf(account),
    )
    assert resp.status_code == 200, resp.text


def _square_ids(client: TestClient, account: dict) -> set[int]:
    _act_as(client, account)
    resp = client.get("/api/scripts/square")
    assert resp.status_code == 200, resp.text
    return {item["id"] for item in resp.json()["items"]}


def _play_to_terminal(client: TestClient, sid: str, account: dict, *, max_steps: int = 20):
    """按阶段提交合法命令直到终局，返回观察到的阶段集合。"""
    observed: set[str] = set()
    for _ in range(max_steps):
        status = client.get(f"/api/sessions/{sid}").json()
        stage = status["stage"]
        observed.add(stage)
        if stage == "ended":
            return observed
        if stage == "stage1_complete":
            body = {
                "session_id": sid,
                "kind": "select_role",
                "payload": {"role_name": status["playable_roles"][0]},
            }
        elif stage == "stage2_reenacting":
            body = {"session_id": sid, "kind": "choose_option", "payload": {"option_id": "0"}}
        elif stage == "stage2_complete":
            body = {"session_id": sid, "kind": "enter_stage3", "payload": {}}
        elif stage == "stage3_extending":
            body = {"session_id": sid, "kind": "choose_option", "payload": {"option_id": "0"}}
        else:
            raise AssertionError(f"未预期阶段 {stage}")
        resp = client.post(
            f"/api/sessions/{sid}/commands", json=body, headers=_csrf(account)
        )
        assert resp.status_code == 200, resp.text
        new_stage = resp.json()["state"]["stage"]
        observed.add(new_stage)
        if new_stage == "ended":
            return observed
    raise AssertionError("未在步数上限内终局")


# ===== 验收：广场可见性 =====


def test_square_visibility_org_and_public(client):
    teacher = _register(client, "sq.teacher@wenjing.local", "广场教师", role="teacher")
    org_script = _make_script(client, teacher, name="同 org 剧本")
    _publish(client, teacher, org_script, "org")
    public_script = _make_script(client, teacher, name="公开剧本")
    _publish(client, teacher, public_script, "public")
    draft_script = _make_script(client, teacher, name="草稿剧本")  # 未发布

    same_org = _register(client, "sq.student@wenjing.local", "同校学生", role="student")
    assert _square_ids(client, same_org) == {org_script, public_script}

    cross_org = _register(client, "sq.outsider@wenjing.local", "外校学生", role="student")
    _move_to_new_org("sq.outsider@wenjing.local")
    assert _square_ids(client, cross_org) == {public_script}

    # 详情：同 org 可见 org 剧本；跨 org 不可见（按不存在处理）
    _act_as(client, same_org)
    assert client.get(f"/api/scripts/{org_script}").status_code == 200
    _act_as(client, cross_org)
    assert client.get(f"/api/scripts/{org_script}").status_code == 404
    assert client.get(f"/api/scripts/{public_script}").status_code == 200
    # 草稿不进广场、对他不可见
    assert client.get(f"/api/scripts/{draft_script}").status_code == 404


# ===== 验收：学生从剧本开局并游玩至终局 =====


def test_student_opens_and_plays_to_stage3_and_terminal(client):
    teacher = _register(client, "play.teacher@wenjing.local", "游玩教师", role="teacher")
    script_id = _make_script(client, teacher, name="可玩剧本")
    _publish(client, teacher, script_id, "public")

    student = _register(client, "play.student@wenjing.local", "游玩学生", role="student")
    _move_to_new_org("play.student@wenjing.local")  # 跨 org 走公开剧本
    _act_as(client, student)

    created = client.post(
        "/api/sessions",
        json={"schema_version": "1.0.0", "script_id": script_id},
        headers=_csrf(student),
    )
    assert created.status_code == 201, created.text
    sid = created.json()["session_id"]
    assert created.json()["stage"] == "stage1_complete"
    assert created.json()["playable_roles"]

    observed = _play_to_terminal(client, sid, student)
    assert "stage2_reenacting" in observed
    assert "stage3_extending" in observed
    assert "ended" in observed
    assert client.get(f"/api/sessions/{sid}").json()["stage"] == "ended"


# ===== 验收：我的游戏与续玩（刷新 / 无状态恢复）=====


def test_my_games_list_and_resume(client):
    teacher = _register(client, "mine.teacher@wenjing.local", "我的教师", role="teacher")
    script_id = _make_script(client, teacher, name="我的游戏剧本")
    _publish(client, teacher, script_id, "public")

    student = _register(client, "mine.student@wenjing.local", "我的学生", role="student")
    _act_as(client, student)
    created = client.post(
        "/api/sessions",
        json={"schema_version": "1.0.0", "script_id": script_id},
        headers=_csrf(student),
    )
    assert created.status_code == 201, created.text
    sid = created.json()["session_id"]

    games = client.get("/api/sessions").json()["items"]
    assert [g["session_id"] for g in games] == [sid]
    assert games[0]["script_name"] == "我的游戏剧本"
    assert games[0]["stage"] == "stage1_complete"

    # 选角：命令路径无状态，每次从 DB 重建
    role = created.json()["playable_roles"][0]
    upd = client.post(
        f"/api/sessions/{sid}/commands",
        json={
            "session_id": sid,
            "kind": "select_role",
            "payload": {"role_name": role},
        },
        headers=_csrf(student),
    )
    assert upd.status_code == 200, upd.text
    assert upd.json()["state"]["stage"] == "stage2_reenacting"

    # 「刷新」：重新查询状态与列表一致
    status = client.get(f"/api/sessions/{sid}").json()
    assert status["stage"] == "stage2_reenacting"
    assert status["selected_role"] == role
    games = client.get("/api/sessions").json()["items"]
    assert games[0]["stage"] == "stage2_reenacting"
    assert games[0]["player_role"] == role

    # WS 重连：session_init 从 DB 重建，与刷新结果一致
    with client.websocket_connect(f"/ws/{sid}") as ws:
        init = ws.receive_json()
    assert init["type"] == "session_init"
    assert init["payload"]["stage"] == "stage2_reenacting"
    assert init["payload"]["player_role"] == role

    # 续玩可用：继续推进
    upd2 = client.post(
        f"/api/sessions/{sid}/commands",
        json={
            "session_id": sid,
            "kind": "choose_option",
            "payload": {"option_id": "0"},
        },
        headers=_csrf(student),
    )
    assert upd2.status_code == 200, upd2.text
    assert upd2.json()["state"]["active_interaction"] is not None


# ===== 验收：教师可游玩自己的剧本（含未发布草稿）=====


def test_teacher_can_play_own_draft(client):
    teacher = _register(client, "own.teacher@wenjing.local", "自玩教师", role="teacher")
    draft = _make_script(client, teacher, name="自玩草稿")
    _act_as(client, teacher)
    created = client.post(
        "/api/sessions",
        json={"schema_version": "1.0.0", "script_id": draft},
        headers=_csrf(teacher),
    )
    assert created.status_code == 201, created.text
    assert created.json()["playable_roles"]

    # 草稿对他人不可见、不可开局
    other = _register(client, "own.other@wenjing.local", "他人", role="student")
    _move_to_new_org("own.other@wenjing.local")
    _act_as(client, other)
    denied = client.post(
        "/api/sessions",
        json={"schema_version": "1.0.0", "script_id": draft},
        headers=_csrf(other),
    )
    assert denied.status_code == 404
    assert denied.json()["code"] == "CONTENT_SCRIPT_NOT_FOUND"


# ===== 拒绝语义 =====


def test_open_session_rejects_bad_requests(client):
    teacher = _register(client, "rej.teacher@wenjing.local", "拒绝教师", role="teacher")
    script_id = _make_script(client, teacher, name="拒绝剧本", generate=False)

    # 未登录
    client.cookies.clear()
    unauth = client.post("/api/sessions", json={"schema_version": "1.0.0", "script_id": 1})
    assert unauth.status_code == 401
    assert client.get("/api/sessions").status_code == 401

    # 已登录但缺 CSRF
    _act_as(client, teacher)
    missing = client.post(
        "/api/sessions", json={"schema_version": "1.0.0", "script_id": 1}
    )
    assert missing.status_code == 403
    assert missing.json()["code"] == "AUTH_CSRF_FAILED"

    # 剧本未生成 → 409
    not_ready = client.post(
        "/api/sessions",
        json={"schema_version": "1.0.0", "script_id": script_id},
        headers=_csrf(teacher),
    )
    assert not_ready.status_code == 409
    assert not_ready.json()["code"] == "CONTENT_SCRIPT_NOT_READY"
