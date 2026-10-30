"""S3 兼容对象存储适配器（ADR-0005 §4，issue #40）。

- 统一 S3 协议：开发 MinIO、生产 OSS/COS，仅 `endpoint_url` 与凭证不同。
- 私有桶：`put` 走**内网 endpoint**；`presign` 用**浏览器可达的 public endpoint**
  单独签名——SigV4 签名覆盖 Host，不能事后重写 host，故必须用独立 client 生成。
- boto3 为同步 SDK：`put`/`presign` 经 `asyncio.to_thread` 避免阻塞事件循环。
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.domain.game.media import ObjectStoragePort
from app.infrastructure.config import Settings
from app.infrastructure.errx import codes, new, wrap
from app.infrastructure.media.null import NullObjectStorage


def _build_client(endpoint: str, access_key: str, secret_key: str, region: str) -> Any:
    """构造 path-style S3v4 客户端（MinIO 非 DNS 桶名需要 path-style）。"""
    import boto3
    from botocore.config import Config

    return boto3.client(
        "s3",
        endpoint_url=endpoint or None,
        aws_access_key_id=access_key or None,
        aws_secret_access_key=secret_key or None,
        region_name=region or "us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )


class S3ObjectStorage:
    """`ObjectStoragePort` 的 S3 兼容实现（MinIO / OSS / COS）。"""

    def __init__(
        self,
        *,
        endpoint: str,
        public_endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "",
        presign_ttl: int = 900,
    ) -> None:
        self.bucket = bucket
        self._presign_ttl = presign_ttl
        self._internal = _build_client(endpoint, access_key, secret_key, region)
        # 预签名必须用 public endpoint 签名（SigV4 覆盖 Host）
        self._public = _build_client(
            public_endpoint or endpoint, access_key, secret_key, region
        )

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None:
        try:
            await asyncio.to_thread(self._put_sync, object_key, data, content_type)
        except Exception as exc:  # noqa: BLE001 - 统一媒体错误域
            raise wrap(
                exc, codes.MEDIA_STORAGE_FAILED, extra={"op": "put", "reason": str(exc)}
            ) from exc

    def _put_sync(self, object_key: str, data: bytes, content_type: str) -> None:
        self._internal.put_object(
            Bucket=self.bucket, Key=object_key, Body=data, ContentType=content_type
        )

    async def presign(self, *, object_key: str, ttl_seconds: int = 900) -> str:
        try:
            return await asyncio.to_thread(self._presign_sync, object_key, ttl_seconds)
        except Exception as exc:  # noqa: BLE001 - 统一媒体错误域
            raise wrap(
                exc,
                codes.MEDIA_STORAGE_FAILED,
                extra={"op": "presign", "reason": str(exc)},
            ) from exc

    def _presign_sync(self, object_key: str, ttl_seconds: int) -> str:
        ttl = ttl_seconds or self._presign_ttl
        return self._public.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": object_key},
            ExpiresIn=ttl,
        )


def build_object_storage(settings: Settings) -> ObjectStoragePort:
    """按配置装配对象存储；provider=null 时为安全空实现。

    provider=s3 但缺少 endpoint/凭证/桶时**启动即报错**（不静默回落到 AWS 默认端点）。
    """
    if settings.media_storage_provider == "s3":
        required = {
            "endpoint": settings.media_storage_endpoint,
            "access_key": settings.media_storage_access_key,
            "secret_key": settings.media_storage_secret_key,
            "bucket": settings.media_storage_bucket,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise new(
                codes.CFG_MEDIA_STORAGE_INCOMPLETE, extra={"missing": ", ".join(missing)}
            )
        return S3ObjectStorage(
            endpoint=settings.media_storage_endpoint,
            public_endpoint=settings.media_storage_public_endpoint,
            access_key=settings.media_storage_access_key,
            secret_key=settings.media_storage_secret_key,
            bucket=settings.media_storage_bucket,
            region=settings.media_storage_region,
            presign_ttl=settings.media_storage_presign_ttl,
        )
    return NullObjectStorage()


__all__ = ["S3ObjectStorage", "build_object_storage"]
