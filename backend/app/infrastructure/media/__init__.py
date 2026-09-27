"""媒体适配器层（ADR-0005 §2）：实现 `domain/game/media.py` 的端口。

M0（#39）只放空实现与配置，不接业务：

- `null`：六个端口的零依赖空实现（未配置真实 provider 时的安全降级）。

后续里程碑在此目录加入真实适配器：`storage_s3`（M1 #40）、`image_search_*`（M2 #44）、
`image_gen_*`（M2 #46）、`asset_repo`（M2 #47）、`image_processor`（M1 #42）。
"""

from __future__ import annotations

from app.infrastructure.media.meter import MediaUsageRecorder
from app.infrastructure.media.null import (
    NullAssetRepository,
    NullImageGen,
    NullImageSearch,
    NullMediaMeter,
    NullMediaQuota,
    NullObjectStorage,
)
from app.infrastructure.media.quota import MediaQuotaService
from app.infrastructure.media.storage_s3 import S3ObjectStorage, build_object_storage

__all__ = [
    "MediaQuotaService",
    "MediaUsageRecorder",
    "NullAssetRepository",
    "NullImageGen",
    "NullImageSearch",
    "NullMediaMeter",
    "NullMediaQuota",
    "NullObjectStorage",
    "S3ObjectStorage",
    "build_object_storage",
]
