"""资产访问与图片多规格测试（issue #42 / ADR-0005 §3/§4）。

- ImageProcessor：多规格 + WebP，非法字节报 MEDIA_IMAGE_INVALID（无 DB）。
- AssetAccessService：授权/404/未就绪（无 DB，fake 端口）。
- GET /api/assets/{id}/url：越权拒绝（PG 集成，同步 TestClient）。
"""

from __future__ import annotations

import asyncio
import os
import uuid
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401
from app.contracts.enums import UserRole
from app.domain.access import Actor
from app.domain.game.media import AssetKind, AssetRecord, AssetStatus
from app.infrastructure.errx import Error, codes, match_code
from app.infrastructure.media import ImageProcessor, SqlAssetRepository
from app.services.assets import AssetAccessService

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)
_REGISTER = {"schema_version": "2.4.0", "phone": None, "password": "supersecret1"}


# ===== ImageProcessor（无 DB）=====


def _png_bytes(size: tuple[int, int] = (800, 600)) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", size, (200, 100, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


def test_image_processor_produces_multisize_webp():
    from PIL import features

    variants = ImageProcessor().process(_png_bytes())
    by_name = {v.name: v for v in variants}
    assert {"thumb.webp", "medium.webp", "original.webp"} <= set(by_name)
    assert by_name["thumb.webp"].width <= 256 and by_name["thumb.webp"].height <= 256
    assert by_name["medium.webp"].width <= 1024
    assert by_name["original.webp"].width == 800
    assert all(v.data for v in variants)
    if features.check("avif"):
        assert {"thumb.avif", "medium.avif", "original.avif"} <= set(by_name)


def test_image_processor_rejects_oversized_pixels():
    with pytest.raises(Error) as excinfo:
        ImageProcessor(max_pixels=10).process(_png_bytes((100, 100)))
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_INVALID)


def test_image_processor_rejects_invalid_bytes():
    with pytest.raises(Error) as excinfo:
        ImageProcessor().process(b"not an image")
    assert match_code(excinfo.value, codes.MEDIA_IMAGE_INVALID)


# ===== AssetAccessService 授权（无 DB，fake 端口）=====


class _FakeRepo:
    def __init__(self, record: AssetRecord | None) -> None:
        self.record = record

    async def save(self, record: AssetRecord) -> AssetRecord:
        self.record = record
        return record

    async def get_by_id(self, asset_id: uuid.UUID) -> AssetRecord | None:
        if self.record is not None and self.record.asset_id == asset_id:
            return self.record
        return None

    async def find_by_dedup_key(self, *, org_id, dedup_key):  # noqa: ANN001, ANN202
        return None


class _FakeStorage:
    async def put(self, *, object_key, data, content_type):  # noqa: ANN001, ANN202
        return None

    async def presign(self, *, object_key: str, ttl_seconds: int = 900) -> str:
        return f"https://cdn.example/{object_key}"


class _FakeSession:
    def __init__(self, rows: dict) -> None:
        self._rows = rows

    async def __aenter__(self):  # noqa: ANN204
        return self

    async def __aexit__(self, *exc):  # noqa: ANN002, ANN204
        return False

    async def get(self, model, pk):  # noqa: ANN001, ANN201
        return self._rows.get((model, pk))


class _FakeSessionFactory:
    """按 (model, pk) 返回预置行；org 分支不使用。"""

    def __init__(self, rows: dict | None = None) -> None:
        self._rows = rows or {}

    def __call__(self) -> _FakeSession:
        return _FakeSession(self._rows)


def _record(
    *,
    org_id: uuid.UUID,
    status: AssetStatus = AssetStatus.READY,
    session_id: uuid.UUID | None = None,
    script_id: int | None = None,
) -> AssetRecord:
    return AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="org/scene-1.webp",
        kind=AssetKind.BACKGROUND,
        status=status,
        org_id=org_id,
        session_id=session_id,
        script_id=script_id,
    )


def _actor(org_id: uuid.UUID, role: UserRole = UserRole.STUDENT, user_id=None) -> Actor:  # noqa: ANN001
    return Actor(user_id=user_id or uuid.uuid4(), org_id=org_id, role=role)


def _service(record, rows=None):  # noqa: ANN001, ANN202
    return AssetAccessService(
        assets=_FakeRepo(record),
        storage=_FakeStorage(),
        session_factory=_FakeSessionFactory(rows),
    )


async def test_service_returns_url_for_same_org():
    org = uuid.uuid4()
    record = _record(org_id=org)
    result = await _service(record).url_for(_actor(org), record.asset_id)
    assert result.url == "https://cdn.example/org/scene-1.webp"
    assert result.asset_id == record.asset_id


async def test_service_forbids_cross_org():
    record = _record(org_id=uuid.uuid4())
    with pytest.raises(Error) as excinfo:
        await _service(record).url_for(_actor(uuid.uuid4()), record.asset_id)
    assert match_code(excinfo.value, codes.AUTH_FORBIDDEN)


async def test_service_missing_asset_is_404():
    with pytest.raises(Error) as excinfo:
        await _service(None).url_for(_actor(uuid.uuid4()), uuid.uuid4())
    assert match_code(excinfo.value, codes.MEDIA_ASSET_NOT_FOUND)


async def test_service_pending_asset_is_not_ready():
    org = uuid.uuid4()
    record = _record(org_id=org, status=AssetStatus.PENDING)
    with pytest.raises(Error) as excinfo:
        await _service(record).url_for(_actor(org), record.asset_id)
    assert match_code(excinfo.value, codes.MEDIA_ASSET_NOT_READY)


async def test_service_session_asset_is_owner_only():
    """运行期资产（session_id）仅会话 owner 可读，同 org 他人也 403。"""
    from types import SimpleNamespace

    from app.infrastructure.models.session import Session as SessionRow

    org = uuid.uuid4()
    owner_id = uuid.uuid4()
    session_id = uuid.uuid4()
    record = _record(org_id=org, session_id=session_id)
    rows = {(SessionRow, session_id): SimpleNamespace(owner_user_id=owner_id)}
    service = _service(record, rows)

    ok = await service.url_for(_actor(org, user_id=owner_id), record.asset_id)
    assert ok.url.endswith(record.object_key)

    with pytest.raises(Error) as excinfo:
        await service.url_for(_actor(org), record.asset_id)
    assert match_code(excinfo.value, codes.AUTH_FORBIDDEN)


async def test_service_script_asset_respects_visibility():
    """生成期资产（script_id）按剧本可见性：草稿仅 owner；公开已发布跨 org 可读。"""
    from types import SimpleNamespace

    from app.infrastructure.models.script import Script as ScriptRow

    org = uuid.uuid4()
    owner_id = uuid.uuid4()
    record = _record(org_id=org, script_id=42)

    draft = SimpleNamespace(
        owner_user_id=owner_id, status="draft", visibility="org", org_id=org
    )
    draft_service = _service(record, {(ScriptRow, 42): draft})
    assert (await draft_service.url_for(_actor(org, user_id=owner_id), record.asset_id)).url
    with pytest.raises(Error) as excinfo:
        await draft_service.url_for(_actor(org), record.asset_id)
    assert match_code(excinfo.value, codes.AUTH_FORBIDDEN)

    published = SimpleNamespace(
        owner_user_id=owner_id, status="published", visibility="public", org_id=org
    )
    public_service = _service(record, {(ScriptRow, 42): published})
    result = await public_service.url_for(_actor(uuid.uuid4()), record.asset_id)
    assert result.url.endswith(record.object_key)



# ===== 端点（PG 集成，同步 TestClient；与 async 仓库测试分模块避免 loop 混用）=====


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


@pytest.fixture(scope="module")
def client():
    if not asyncio.run(_db_available()):
        pytest.skip("PostgreSQL 未可用，跳过资产端点集成测试")
    engine = _engine()

    from conftest import drop_baseline_schema, reset_baseline_schema

    async def _reset() -> None:
        async with engine.begin() as conn:
            await reset_baseline_schema(conn)

    asyncio.run(_reset())
    asyncio.run(engine.dispose())

    from app.infrastructure.db import session as db_session
    from app.main import create_app

    # app 的 DB engine 绑定事件循环；释放前序 TestClient 模块遗留的连接池，
    # 否则跨模块复用会触发 asyncpg「another operation in progress」。
    asyncio.run(db_session.engine.dispose())
    app = create_app()
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        asyncio.run(db_session.engine.dispose())
        teardown_engine = _engine()

        async def _teardown() -> None:
            async with teardown_engine.begin() as conn:
                await drop_baseline_schema(conn)

        asyncio.run(_teardown())
        asyncio.run(teardown_engine.dispose())


def _register(client: TestClient, email: str) -> dict:
    client.cookies.clear()
    resp = client.post(
        "/api/auth/register",
        json={**_REGISTER, "email": email, "nickname": "资产用户"},
    )
    assert resp.status_code == 201, resp.text
    return client.get("/api/auth/me").json()


def _insert_asset(*, org_id: uuid.UUID, status: str = "ready") -> uuid.UUID:
    """用独立引擎/事件循环插入资产（不与 async 夹具共享引擎）。"""
    asset_id = uuid.uuid4()

    async def _run() -> None:
        engine = _engine()
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        try:
            await SqlAssetRepository(session_factory=factory).save(
                AssetRecord(
                    asset_id=asset_id,
                    object_key=f"org/{asset_id}.webp",
                    kind=AssetKind.BACKGROUND,
                    status=AssetStatus(status),
                    org_id=org_id,
                )
            )
        finally:
            await engine.dispose()

    asyncio.run(_run())
    return asset_id


def _move_to_new_org(email: str) -> None:
    async def _run() -> None:
        engine = _engine()
        try:
            async with engine.begin() as conn:
                oid = uuid.uuid4()
                await conn.execute(
                    text("insert into orgs (id, name, created_at) values (:id, :name, now())"),
                    {"id": oid, "name": f"isolated-{oid}"},
                )
                await conn.execute(
                    text("update users set org_id = :oid where email = :email"),
                    {"oid": oid, "email": email},
                )
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_asset_url_same_org_ok(client):
    me = _register(client, "asset-owner@wenjing.local")
    asset_id = _insert_asset(org_id=uuid.UUID(me["org_id"]))
    resp = client.get(f"/api/assets/{asset_id}/url")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["asset_id"] == str(asset_id)
    # provider=null 时为空实现；s3 时为预签名 URL
    assert body["url"] == "" or body["url"].startswith("http")
    assert body["expires_at"]


def test_asset_url_unknown_is_404(client):
    _register(client, "asset-404@wenjing.local")
    resp = client.get(f"/api/assets/{uuid.uuid4()}/url")
    assert resp.status_code == 404
    assert resp.json()["code"] == "MEDIA_ASSET_NOT_FOUND"


def test_asset_url_unauthenticated_is_401(client):
    client.cookies.clear()
    resp = client.get(f"/api/assets/{uuid.uuid4()}/url")
    assert resp.status_code == 401


def test_asset_url_cross_org_is_403(client):
    owner = _register(client, "asset-cross-owner@wenjing.local")
    asset_id = _insert_asset(org_id=uuid.UUID(owner["org_id"]))

    _register(client, "asset-cross-other@wenjing.local")
    _move_to_new_org("asset-cross-other@wenjing.local")
    resp = client.get(f"/api/assets/{asset_id}/url")
    assert resp.status_code == 403
    assert resp.json()["code"] == "AUTH_FORBIDDEN"
