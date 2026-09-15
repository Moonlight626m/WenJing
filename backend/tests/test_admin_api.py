"""运营后台 API 集成测试（issue #22 / ADR-0002 §5）。

覆盖验收：
- 仅 `super_admin` 可访问后台 API（教师/学生 403）；
- 剧本库列表跨 org，可按 org/status 过滤；
- token 用量聚合按 org / 用途过滤；
- 教师不可见学生/其他教师数据。

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
    async def _run() -> None:
        engine = _engine()
        try:
            async with engine.begin() as conn:
                await conn.execute(text(sql), params)
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _move_to_new_org(email: str) -> None:
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


def _insert_usage(account: dict, *, purpose: str, total: int, calls: int = 1) -> None:
    """直接插入用量行（测试读路径的确定性数据）。"""
    me = account["me"]
    for _ in range(calls):
        _execute(
            "insert into llm_usage "
            "(provider, model, purpose, prompt_tokens, completion_tokens, "
            " total_tokens, org_id, user_id, created_at) "
            "values ('test', 'test-model', :purpose, :prompt, :completion, "
            " :total, :org, :uid, now())",
            purpose=purpose,
            prompt=total // 2,
            completion=total - total // 2,
            total=total,
            org=me["org_id"],
            uid=me["id"],
        )


@pytest.fixture(scope="module")
def client():
    if not asyncio.run(_db_available()):
        pytest.skip("PostgreSQL 未可用，跳过运营后台 API 集成测试")
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

    # app 的 DB engine/连接池绑定事件循环：跨 TestClient 模块复用会触发
    # "attached to a different loop"。创建前释放前序遗留，销毁后释放自身。
    from app.db import session as db_session

    asyncio.run(db_session.engine.dispose())
    app = create_app()
    try:
        with TestClient(app) as c:
            yield c
    finally:
        asyncio.run(db_session.engine.dispose())
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


def _make_script(client: TestClient, account: dict, *, name: str, publish: bool = True) -> int:
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

    async def _gen() -> None:
        from app.access import Actor
        from app.scripts.service import ScriptLibrary

        eng = _engine()
        factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
        try:
            actor = Actor(
                user_id=uuid.UUID(account["me"]["id"]),
                org_id=uuid.UUID(account["me"]["org_id"]),
                role=UserRole(account["me"]["role"]),
            )
            library = ScriptLibrary(session_factory=factory, script_llm=None)
            await library.start_generation(script_id, actor)
            await library.await_generation(script_id)
        finally:
            await eng.dispose()

    asyncio.run(_gen())
    if publish:
        resp = client.post(
            f"/api/scripts/{script_id}/publish",
            json={"schema_version": "1.0.0", "visibility": "org"},
            headers=_csrf(account),
        )
        assert resp.status_code == 200, resp.text
    return script_id


# ===== 验收：仅 super_admin 可访问 =====


def test_admin_endpoints_require_super_admin(client):
    admin = _register(client, "adm.admin@wenjing.local", "超管", role="super_admin")
    teacher = _register(client, "adm.teacher@wenjing.local", "教师", role="teacher")
    student = _register(client, "adm.student@wenjing.local", "学生", role="student")

    for account in (teacher, student):
        _act_as(client, account)
        assert client.get("/api/admin/usage").status_code == 403
        assert client.get("/api/admin/scripts").status_code == 403
        assert client.get("/api/admin/usage").json()["code"] == "AUTH_FORBIDDEN"

    client.cookies.clear()
    assert client.get("/api/admin/usage").status_code == 401

    _act_as(client, admin)
    assert client.get("/api/admin/usage").status_code == 200
    assert client.get("/api/admin/scripts").status_code == 200


# ===== 验收：剧本库列表跨 org =====


def test_admin_script_list_covers_orgs(client):
    admin = _register(client, "lst.admin@wenjing.local", "列表超管", role="super_admin")
    teacher_a = _register(client, "lst.a@wenjing.local", "甲教师", role="teacher")
    script_a = _make_script(client, teacher_a, name="甲校剧本")

    teacher_b = _register(client, "lst.b@wenjing.local", "乙教师", role="teacher")
    _move_to_new_org("lst.b@wenjing.local")
    teacher_b = {
        "session": client.cookies.get("wenjing_session"),
        "csrf": client.cookies.get("wenjing_csrf"),
        "me": client.get("/api/auth/me").json(),
    }
    script_b = _make_script(client, teacher_b, name="乙校剧本")

    _act_as(client, admin)
    items = client.get("/api/admin/scripts").json()["items"]
    ids = {item["id"] for item in items}
    assert {script_a, script_b} <= ids
    assert {item["name"] for item in items if item["id"] in {script_a, script_b}} == {
        "甲校剧本",
        "乙校剧本",
    }

    # 按 org 过滤
    only_b = client.get(
        f"/api/admin/scripts?org_id={teacher_b['me']['org_id']}"
    ).json()["items"]
    assert {item["id"] for item in only_b} == {script_b}


# ===== 验收：教师不可见其他 org / 后台数据 =====


def test_teacher_cannot_see_others_data(client):
    teacher_a = _register(client, "iso.a@wenjing.local", "隔离甲", role="teacher")
    script_a = _make_script(client, teacher_a, name="隔离甲剧本")

    # 学生开局：会话仅 owner 可见，教师（即便同 org / 是剧本作者）不可见
    student = _register(client, "iso.student@wenjing.local", "隔离学生", role="student")
    _act_as(client, student)
    created = client.post(
        "/api/sessions",
        json={"schema_version": "1.0.0", "script_id": script_a},
        headers=_csrf(student),
    )
    assert created.status_code == 201, created.text
    sid = created.json()["session_id"]

    _act_as(client, teacher_a)
    assert client.get(f"/api/sessions/{sid}").status_code == 403
    assert all(
        g["session_id"] != sid for g in client.get("/api/sessions").json()["items"]
    )

    teacher_b = _register(client, "iso.b@wenjing.local", "隔离乙", role="teacher")
    _move_to_new_org("iso.b@wenjing.local")
    _act_as(client, teacher_b)

    # 教师剧本库仅自己
    own = client.get("/api/scripts").json()["items"]
    assert {item["id"] for item in own} == set()
    # 无后台访问权
    assert client.get("/api/admin/usage").status_code == 403
    # 不可见他人（不可见 org）剧本详情
    assert client.get(f"/api/scripts/{script_a}").status_code == 404


# ===== 验收：token 聚合按 org / 用途过滤 =====


def test_admin_usage_aggregation(client):
    admin = _register(client, "agg.admin@wenjing.local", "聚合超管", role="super_admin")
    org_a = _register(client, "agg.a@wenjing.local", "聚合甲", role="teacher")
    _insert_usage(org_a, purpose="stage1", total=1000, calls=2)
    _insert_usage(org_a, purpose="agent", total=600, calls=3)

    org_b = _register(client, "agg.b@wenjing.local", "聚合乙", role="teacher")
    _move_to_new_org("agg.b@wenjing.local")
    org_b = {
        "session": client.cookies.get("wenjing_session"),
        "csrf": client.cookies.get("wenjing_csrf"),
        "me": client.get("/api/auth/me").json(),
    }
    _insert_usage(org_b, purpose="stage1", total=2000, calls=1)

    _act_as(client, admin)
    rows = client.get("/api/admin/usage").json()["items"]
    by_key = {(r["org_id"], r["purpose"]): r for r in rows}

    a_stage1 = by_key[(org_a["me"]["org_id"], "stage1")]
    assert a_stage1["call_count"] == 2
    assert a_stage1["total_tokens"] == 2000
    agent = by_key[(org_a["me"]["org_id"], "agent")]
    assert agent["call_count"] == 3 and agent["total_tokens"] == 1800
    b_stage1 = by_key[(org_b["me"]["org_id"], "stage1")]
    assert b_stage1["call_count"] == 1 and b_stage1["total_tokens"] == 2000

    # 按 org 过滤
    filtered = client.get(
        f"/api/admin/usage?org_id={org_a['me']['org_id']}"
    ).json()["items"]
    assert {r["purpose"] for r in filtered} == {"stage1", "agent"}
    # 按用途过滤
    only_agent = client.get("/api/admin/usage?purpose=agent").json()["items"]
    assert all(r["purpose"] == "agent" for r in only_agent)

    # 时间窗之外为空
    future = client.get("/api/admin/usage?since=2999-01-01T00:00:00Z").json()["items"]
    assert future == []
