"""对象存储 S3 adapter 测试（issue #40 / ADR-0005 §4）。

- 工厂与端口形状（无外部依赖）。
- 预签名使用 public endpoint（离线签名，验证内外网 endpoint 分离）。
- MinIO 集成：上传 → 预签名 → 下载字节一致（MinIO 不可用则 skip）。
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest

from app.domain.game.media import ObjectStoragePort
from app.infrastructure.config import Settings
from app.infrastructure.media import (
    NullObjectStorage,
    S3ObjectStorage,
    build_object_storage,
)

_ENDPOINT = os.environ.get("WENJING_MEDIA_STORAGE_ENDPOINT", "http://localhost:9000")
_BUCKET = os.environ.get("WENJING_MEDIA_STORAGE_BUCKET", "wenjing-media")
_ACCESS_KEY = os.environ.get("WENJING_MEDIA_STORAGE_ACCESS_KEY", "wenjing")
_SECRET_KEY = os.environ.get("WENJING_MEDIA_STORAGE_SECRET_KEY", "wenjing123")
# WENJING_TEST_MINIO=1 时 MinIO 不可用即失败（CI 应显式开启，避免静默 skip 假绿）
_REQUIRE_MINIO = os.environ.get("WENJING_TEST_MINIO") == "1"


def test_build_object_storage_null_by_default():
    storage = build_object_storage(Settings(media_storage_provider="null"))
    assert isinstance(storage, NullObjectStorage)


def test_build_object_storage_s3_requires_credentials():
    """provider=s3 但配置不全时启动即报错（不静默回落 AWS 默认端点）。"""
    from app.infrastructure.errx import Error

    with pytest.raises(Error):
        build_object_storage(Settings(media_storage_provider="s3"))


def test_build_object_storage_s3_satisfies_port():
    storage = build_object_storage(
        Settings(
            media_storage_provider="s3",
            media_storage_endpoint="http://localhost:9000",
            media_storage_public_endpoint="http://localhost:9000",
            media_storage_bucket="b",
            media_storage_access_key="k",
            media_storage_secret_key="s",
        )
    )
    assert isinstance(storage, ObjectStoragePort)


async def test_presign_uses_public_endpoint():
    """内网 endpoint 与 public endpoint 分离：预签名 URL 用 public 主机签名。"""
    storage = S3ObjectStorage(
        endpoint="http://minio:9000",
        public_endpoint="http://localhost:9000",
        access_key="k",
        secret_key="s",
        bucket="b",
    )
    url = await storage.presign(object_key="a/b.png", ttl_seconds=60)
    assert url.startswith("http://localhost:9000/")
    assert "X-Amz-Signature" in url


async def _minio_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            resp = await client.get(f"{_ENDPOINT}/minio/health/live")
        return resp.status_code == 200
    except Exception:
        return False


async def test_minio_put_and_presigned_download():
    if not await _minio_available():
        if _REQUIRE_MINIO:
            pytest.fail(f"WENJING_TEST_MINIO=1 但 MinIO 不可用（{_ENDPOINT}）")
        pytest.skip(f"MinIO 未可用（{_ENDPOINT}），跳过对象存储集成测试")

    storage = S3ObjectStorage(
        endpoint=_ENDPOINT,
        public_endpoint=_ENDPOINT,
        access_key=_ACCESS_KEY,
        secret_key=_SECRET_KEY,
        bucket=_BUCKET,
    )
    key = f"test/{uuid.uuid4().hex}.txt"
    data = b"hello wenjing media"

    await storage.put(object_key=key, data=data, content_type="text/plain")
    url = await storage.presign(object_key=key, ttl_seconds=60)
    assert url.startswith(_ENDPOINT)

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url)
    assert resp.status_code == 200
    assert resp.content == data
