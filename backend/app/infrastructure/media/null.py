"""媒体端口空实现（ADR-0005 §2，issue #39 M0）。

未配置真实 provider / 存储时使用：可安全调用、不触网、不上传，产出空结果让上层降级。
真实适配器在 M1/M2 按里程碑替换（#40/#44/#46/#47）。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from app.domain.game.asr import Transcript
from app.domain.game.media import (
    AssetKind,
    AssetRecord,
    AssetStatus,
    GeneratedImage,
    ImageCandidate,
    MediaKind,
    MediaUsage,
)
from app.domain.game.tts import SynthesizedAudio, VoiceProfile


class NullObjectStorage:
    """不落盘的 `ObjectStoragePort`：put 为空操作，presign 返回空串。"""

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None:
        return None

    async def presign(self, *, object_key: str, ttl_seconds: int = 900) -> str:
        return ""


class NullImageGen:
    """不调 provider 的 `ImageGenPort`：返回空字节，由上层降级为无图。"""

    async def generate(
        self,
        *,
        prompt: str,
        kind: AssetKind,
        width: int = 0,
        height: int = 0,
    ) -> GeneratedImage:
        return GeneratedImage(image_bytes=b"")


class NullImageSearch:
    """不检索的 `ImageSearchPort`：始终返回空候选。"""

    async def search(self, *, query: str, limit: int = 4) -> list[ImageCandidate]:
        return []


class NullAssetRepository:
    """不持久化的 `AssetRepositoryPort`：save 原样返回，查询恒空。"""

    async def save(self, record: AssetRecord) -> AssetRecord:
        return record

    async def get_by_id(self, asset_id: uuid.UUID) -> AssetRecord | None:
        return None

    async def find_by_dedup_key(
        self,
        *,
        org_id: uuid.UUID,
        dedup_key: str,
        status: AssetStatus | None = None,
    ) -> AssetRecord | None:
        return None

    async def fail_stale_pending(self, *, before: datetime) -> int:
        return 0


class NullMediaMeter:
    """不落库的 `MediaMeterPort`（best-effort 语义下即为空操作）。"""

    async def record(self, usage: MediaUsage) -> None:
        return None


class NullMediaQuota:
    """不设限的 `MediaQuotaPort`：check 恒真、consume 空操作。"""

    async def try_acquire(
        self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1
    ) -> bool:
        return True

    async def check(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> bool:
        return True

    async def consume(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> None:
        return None


class NullTts:
    """不合成的 `TtsPort`：返回空字节，上层（`TtsSynthesizer`）据此静默跳过。

    返回空字节而不是抛错：无 key 的开发/测试环境里不该刷满合成失败告警——"没配
    provider"是预期状态，不是故障（与其余 null adapter 同一约定）。
    """

    async def synthesize(self, *, text: str, voice: VoiceProfile) -> SynthesizedAudio:
        return SynthesizedAudio(audio_bytes=b"", provider="null")

    async def aclose(self) -> None:
        return None


class NullAsr:
    """不转写的 `AsrPort`：返回空文本。

    与 `NullTts` 不同，它**不静默成功**——`AsrTranscriber` 收到空文本会判
    `MEDIA_ASR_INVALID`。语音是**输入**通道：没识别出东西还假装成功，等于把学生
    的话吞掉，前端也没机会提示改用键盘（#64 验收三）。
    """

    async def transcribe(
        self, *, audio: bytes, content_type: str, language: str = ""
    ) -> Transcript:
        return Transcript(provider="null")

    async def aclose(self) -> None:
        return None


__all__ = [
    "NullAsr",
    "NullAssetRepository",
    "NullTts",
    "NullImageGen",
    "NullImageSearch",
    "NullMediaMeter",
    "NullMediaQuota",
    "NullObjectStorage",
]
