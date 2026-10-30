"""媒体适配器层（ADR-0005 §2）：实现 `domain/game/media.py` 的端口。

M0（#39）只放空实现与配置，不接业务：

- `null`：六个端口的零依赖空实现（未配置真实 provider 时的安全降级）。

后续里程碑在此目录加入真实适配器：`storage_s3`（M1 #40）、`image_search_*`（M2 #44）、
`image_gen_*`（M2 #46）、`asset_repo`（M2 #47）、`image_processor`（M1 #42）。
"""

from __future__ import annotations

from app.infrastructure.media.asr import build_asr
from app.infrastructure.media.asr_openai import OpenAITranscriber
from app.infrastructure.media.asset_jobs import SqlAssetJobStore
from app.infrastructure.media.asset_repo import SqlAssetRepository
from app.infrastructure.media.image_gen import build_image_gen
from app.infrastructure.media.image_gen_openai import OpenAIImageGen
from app.infrastructure.media.image_processor import ImageProcessor
from app.infrastructure.media.image_search import build_image_search
from app.infrastructure.media.image_search_openverse import OpenverseImageSearch
from app.infrastructure.media.image_search_wikimedia import WikimediaImageSearch
from app.infrastructure.media.meter import MediaUsageRecorder
from app.infrastructure.media.null import (
    NullAsr,
    NullAssetRepository,
    NullImageGen,
    NullImageSearch,
    NullMediaMeter,
    NullMediaQuota,
    NullObjectStorage,
    NullTts,
)
from app.infrastructure.media.quota import MediaQuotaService
from app.infrastructure.media.storage_s3 import S3ObjectStorage, build_object_storage
from app.infrastructure.media.tts import build_tts, build_voice_map
from app.infrastructure.media.tts_openai import OpenAITts

__all__ = [
    "ImageProcessor",
    "MediaQuotaService",
    "MediaUsageRecorder",
    "NullAsr",
    "NullAssetRepository",
    "NullImageGen",
    "NullImageSearch",
    "NullMediaMeter",
    "NullMediaQuota",
    "NullObjectStorage",
    "NullTts",
    "OpenAIImageGen",
    "OpenAITranscriber",
    "OpenAITts",
    "OpenverseImageSearch",
    "S3ObjectStorage",
    "SqlAssetJobStore",
    "SqlAssetRepository",
    "WikimediaImageSearch",
    "build_asr",
    "build_image_gen",
    "build_image_search",
    "build_object_storage",
    "build_tts",
    "build_voice_map",
]
