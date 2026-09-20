"""剧本库教师创作 API 集成测试（issue #19 / ADR-0002 §3，真实 PG + fake LLM）。

覆盖验收：
- 教师导入素材 → 建草稿 → 生成 → 发布（org/public）/下架 → 列表/详情；
- 草稿可删除/重新生成；同一素材可生成多个独立剧本；
- 发布后核心内容不可编辑（仅可改可见性/下架）；仅草稿可删除；
- 学生角色调用创作/发布端点被拒（403）；跨 org 可见性规则。

依赖真实 PostgreSQL；不可用时 skip。

注：异步生成在进程内 asyncio 任务中运行，TestClient 下轮询不稳定；本测试用
`_generate_direct`（同一 DB 上以独立事件循环 await 生成）准备已完成剧本，
HTTP 只验证 API 表面与状态机。
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
from app.access import Actor
from app.contracts.enums import UserRole
from app.main import create_app
from app.scripts.service import ScriptLibrary

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)

_MATERIAL_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)

_REGISTER = {"schema_version": "1.0.0", "phone": None, "password": "supersecret1"}


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
        pytest.skip("PostgreSQL 未可用，跳过剧本库集成测试")

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
    _execute(
        "truncate table commands, snapshots, events, event_branches, sessions, "
        "materials, scripts, auth_sessions, users, orgs restart identity cascade"
    )
    client.cookies.clear()
    yield


def _register(client: TestClient, email: str, role: str = "teacher") -> dict:
    client.cookies.clear()
    resp = client.post(
        "/api/auth/register", json={**_REGISTER, "email": email, "nickname": "用户"}
    )
    assert resp.status_code == 201, resp.text
    if role != "student":
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


def _csrf_header(client: TestClient) -> dict[str, str]:
    return {"X-CSRF-Token": client.cookies.get("wenjing_csrf")}


def _post(client: TestClient, url: str, json: dict | None = None):
    return client.post(url, json=json, headers=_csrf_header(client))


def _delete(client: TestClient, url: str):
    return client.delete(url, headers=_csrf_header(client))


def _import_material(client: TestClient) -> int:
    resp = _post(
        client,
        "/api/materials",
        {
            "schema_version": "1.0.0",
            "source": "paste",
            "filename": None,
            "raw_text": _MATERIAL_TEXT,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _create_script(client: TestClient, material_id: int, name: str = "剧本") -> int:
    resp = _post(
        client,
        "/api/scripts",
        {
            "schema_version": "1.0.0",
            "material_id": material_id,
            "name": name,
            "description": None,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def _generate_direct(client: TestClient, script_id: int) -> None:
    """在独立事件循环里 await 生成（确定性 fake），避免 TestClient 后台任务竞态。"""
    me = client.get("/api/auth/me").json()

    async def _run():
        engine = _engine()
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
            progress = await library.progress(script_id)
            assert progress and progress.status == "succeeded", progress
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _publish(client: TestClient, script_id: int, visibility: str = "org"):
    return _post(
        client,
        f"/api/scripts/{script_id}/publish",
        {"schema_version": "1.0.0", "visibility": visibility},
    )


# ===== 教师创作流程 =====


def test_teacher_full_flow(client):
    _register(client, "teacher@wenjing.local")

    material_id = _import_material(client)
    script_id = _create_script(client, material_id)

    detail = client.get(f"/api/scripts/{script_id}").json()
    assert detail["script"]["status"] == "draft"
    assert detail["package"] is None

    _generate_direct(client, script_id)
    detail = client.get(f"/api/scripts/{script_id}").json()
    assert detail["package"] is not None
    assert detail["script"]["status"] == "draft"

    published = _publish(client, script_id, "org")
    assert published.status_code == 200
    assert published.json()["status"] == "published"

    student = _register(client, "student@wenjing.local", role="student")
    _act_as(client, student)
    seen = client.get(f"/api/scripts/{script_id}")
    assert seen.status_code == 200
    assert seen.json()["package"] is not None
    assert seen.json()["generation"] is None  # 非 owner 不暴露生成进度

    # 重新以 owner 身份登录（注册新人会覆盖 cookie），下架后学生不再可见
    owner = _login_owner(client, "teacher@wenjing.local")
    _act_as(client, owner)
    off = _post(client, f"/api/scripts/{script_id}/unpublish")
    assert off.status_code == 200
    assert off.json()["status"] == "unpublished"
    _act_as(client, student)
    assert client.get(f"/api/scripts/{script_id}").status_code == 404


def _login_owner(client: TestClient, email: str) -> dict:
    client.cookies.clear()
    resp = client.post(
        "/api/auth/login",
        json={
            "schema_version": "1.0.0",
            "identifier": email,
            "password": "supersecret1",
        },
    )
    assert resp.status_code == 200, resp.text
    me = client.get("/api/auth/me").json()
    return {
        "session": client.cookies.get("wenjing_session"),
        "csrf": client.cookies.get("wenjing_csrf"),
        "me": me,
    }


def test_generate_endpoint_accepts(client):
    _register(client, "teacher-gen@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)

    started = _post(client, f"/api/scripts/{script_id}/generate")
    assert started.status_code == 202
    # 路由同步写入 running 进度，详情立即可轮询（完成与否无所谓）
    detail = client.get(f"/api/scripts/{script_id}").json()
    assert detail["generation"] is not None
    assert detail["generation"]["status"] in ("running", "succeeded")


def test_same_material_multiple_independent_scripts(client):
    _register(client, "teacher2@wenjing.local")
    material_id = _import_material(client)
    a = _create_script(client, material_id, name="甲")
    b = _create_script(client, material_id, name="乙")
    _generate_direct(client, a)
    _generate_direct(client, b)

    listing = client.get("/api/scripts").json()["items"]
    ids = {item["id"] for item in listing}
    assert {a, b} <= ids


def test_publish_requires_generated_content(client):
    _register(client, "teacher3@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)

    resp = _publish(client, script_id, "public")
    assert resp.status_code == 409
    assert resp.json()["code"] == "CONTENT_SCRIPT_NOT_EDITABLE"


def test_regenerate_and_delete_draft(client):
    _register(client, "teacher4@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)
    _generate_direct(client, script_id)

    regen = _post(client, f"/api/scripts/{script_id}/regenerate")
    assert regen.status_code == 202
    # 清空内容并重启生成
    assert regen.json()["package"] is None
    assert regen.json()["generation"]["status"] in ("running", "succeeded")

    assert _delete(client, f"/api/scripts/{script_id}").status_code == 204
    assert client.get(f"/api/scripts/{script_id}").status_code == 404


def test_published_script_cannot_be_deleted(client):
    _register(client, "teacher5@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)
    _generate_direct(client, script_id)
    _publish(client, script_id, "org")

    resp = _delete(client, f"/api/scripts/{script_id}")
    assert resp.status_code == 409
    assert resp.json()["code"] == "CONTENT_SCRIPT_NOT_EDITABLE"


def test_published_script_cannot_be_regenerated(client):
    _register(client, "teacher8@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)
    _generate_direct(client, script_id)
    _publish(client, script_id, "org")

    resp = _post(client, f"/api/scripts/{script_id}/generate")
    assert resp.status_code == 409
    assert resp.json()["code"] == "CONTENT_SCRIPT_NOT_EDITABLE"


def test_other_teacher_cannot_modify_script(client):
    _register(client, "teacher9@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)
    _generate_direct(client, script_id)

    other = _register(client, "teacher10@wenjing.local")
    _act_as(client, other)
    assert _post(client, f"/api/scripts/{script_id}/generate").status_code == 403
    assert _publish(client, script_id, "public").status_code == 403
    assert _delete(client, f"/api/scripts/{script_id}").status_code == 403


def test_import_non_narrative_rejected(client):
    _register(client, "teacher12@wenjing.local")
    resp = _post(
        client,
        "/api/materials",
        {
            "schema_version": "1.0.0",
            "source": "paste",
            "filename": None,
            "raw_text": "地球绕太阳公转。水由氢和氧组成。光速约为每秒三十万公里。",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "CONTENT_UNSUPPORTED_GENRE"


# ===== 可见性 =====


def test_public_script_visible_cross_org(client):
    _register(client, "teacher7@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)
    _generate_direct(client, script_id)
    _publish(client, script_id, "public")

    outsider = _register(client, "outsider@wenjing.local", role="student")
    _move_to_new_org("outsider@wenjing.local")
    _act_as(client, outsider)
    assert client.get(f"/api/scripts/{script_id}").status_code == 200


def test_org_visibility_hidden_from_other_org(client):
    _register(client, "teacher11@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)
    _generate_direct(client, script_id)
    _publish(client, script_id, "org")

    outsider = _register(client, "outsider2@wenjing.local", role="student")
    _move_to_new_org("outsider2@wenjing.local")
    _act_as(client, outsider)
    assert client.get(f"/api/scripts/{script_id}").status_code == 404


def _move_to_new_org(email: str) -> None:
    _execute(
        "insert into orgs (id, name, created_at) values (:id, :name, now())",
        id=uuid.uuid4(),
        name=f"isolated-{uuid.uuid4().hex[:8]}",
    )
    _execute(
        "update users set org_id = "
        "(select id from orgs order by created_at desc limit 1) where email = :e",
        e=email,
    )


# ===== RBAC =====


def test_student_cannot_use_creation_endpoints(client):
    _register(client, "teacher6@wenjing.local")
    material_id = _import_material(client)
    script_id = _create_script(client, material_id)

    student = _register(client, "student2@wenjing.local", role="student")
    _act_as(client, student)

    import_denied = _post(
        client,
        "/api/materials",
        {
            "schema_version": "1.0.0",
            "source": "paste",
            "filename": None,
            "raw_text": _MATERIAL_TEXT,
        },
    )
    assert import_denied.status_code == 403
    assert import_denied.json()["code"] == "AUTH_FORBIDDEN"

    create_denied = _post(
        client,
        "/api/scripts",
        {
            "schema_version": "1.0.0",
            "material_id": material_id,
            "name": "x",
            "description": None,
        },
    )
    assert create_denied.status_code == 403
    assert _post(client, f"/api/scripts/{script_id}/generate").status_code == 403
    assert _publish(client, script_id, "org").status_code == 403
    assert client.get("/api/scripts").status_code == 403
