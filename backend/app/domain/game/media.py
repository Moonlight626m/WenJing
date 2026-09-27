"""媒体端口与场景资产编排骨架（ADR-0005 §2/§6，issue #39 M0）。

本模块只定义：

- **六个 domain 端口**（infra 提供适配器）：
  `ObjectStoragePort` / `ImageGenPort` / `ImageSearchPort` /
  `AssetRepositoryPort` / `MediaMeterPort` / `MediaQuotaPort`。
- 端口间传递的**领域数据结构**（不落契约，契约 `AssetRef`/`AssetCredit` 见 #43）。
- `SceneDesigner` 骨架：检索→审核→回退生成→存储→产出的编排组件，
  实现留待 M2（#47）。

分层约束：domain 不 import infrastructure；适配器在 `infrastructure/media/`。
本模块 M0 阶段**不接业务、不改变现有行为**。
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable


class AssetKind(StrEnum):
    """资产类别：场景背景 / 角色头像 / 立绘（游玩内只用背景，其余详情页）。"""

    BACKGROUND = "background"
    AVATAR = "avatar"
    FULLBODY = "fullbody"


class AssetStatus(StrEnum):
    """资产持久化状态：先落 pending → 上传对象 → ready（失败 failed）。"""

    PENDING = "pending"
    READY = "ready"
    FAILED = "failed"


class MediaKind(StrEnum):
    """媒体计量类别（ADR-0005 §12）：与 token 语义的 `llm_usage` 分离。"""

    IMAGE = "image"
    TTS = "tts"
    ASR = "asr"


class AssetSource(StrEnum):
    """资产来源：开放版权检索 / 文生图 / 教师上传。"""

    SEARCH = "search"
    GENERATED = "generated"
    UPLOADED = "uploaded"


@dataclass(frozen=True)
class AssetCredit:
    """署名/许可元数据（开放版权合规，ADR-0005 §6）。

    与契约层的 `AssetCredit`（#43）字段对齐，供署名展示与许可过滤使用。
    """

    author: str = ""
    license: str = ""
    source_url: str = ""
    license_url: str = ""


@dataclass(frozen=True)
class ImageCandidate:
    """开放版权库检索的单条候选：字节 + 许可元数据。"""

    image_bytes: bytes
    content_type: str = "image/jpeg"
    source_url: str = ""
    width: int = 0
    height: int = 0
    credit: AssetCredit = field(default_factory=AssetCredit)


@dataclass(frozen=True)
class GeneratedImage:
    """文生图结果。"""

    image_bytes: bytes
    content_type: str = "image/png"
    width: int = 0
    height: int = 0


@dataclass
class AssetRecord:
    """`assets` 表的领域投影（含 object_key；契约层只暴露稳定 `AssetRef`）。

    `object_key` 只在本记录与 `ObjectStoragePort` 内部流转，不进契约/投影。
    """

    asset_id: uuid.UUID
    object_key: str
    kind: AssetKind
    status: AssetStatus = AssetStatus.PENDING
    source: AssetSource = AssetSource.GENERATED
    provider: str = ""
    model: str = ""
    credit: AssetCredit = field(default_factory=AssetCredit)
    content_hash: str = ""
    width: int = 0
    height: int = 0
    org_id: uuid.UUID | None = None
    script_id: int | None = None
    session_id: uuid.UUID | None = None
    dedup_key: str = ""
    version: int = 1
    created_at: datetime | None = None


@dataclass(frozen=True)
class MediaUsage:
    """一次媒体调用的计量事实（best-effort 写 `media_usage`）。"""

    kind: MediaKind
    provider: str
    model: str = ""
    units: int = 1
    size: int = 0
    org_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    script_id: int | None = None
    session_id: uuid.UUID | None = None
    meta: dict[str, object] = field(default_factory=dict)


@runtime_checkable
class ObjectStoragePort(Protocol):
    """对象存储端口（ADR-0005 §2）：put / presign。

    `delete` 待生命周期立项（#57 之后）再定义；读取仅供 infra 内部处理使用。
    预签名 URL 由鉴权端点签发（M1-3 #42），本端口只负责生成。
    """

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None: ...

    async def presign(self, *, object_key: str, ttl_seconds: int = 900) -> str: ...


@runtime_checkable
class ImageGenPort(Protocol):
    """文生图端口（外部 provider）：背景 16:9、头像 1:1，不含人物。"""

    async def generate(
        self,
        *,
        prompt: str,
        kind: AssetKind,
        width: int = 0,
        height: int = 0,
    ) -> GeneratedImage: ...


@runtime_checkable
class ImageSearchPort(Protocol):
    """开放版权库检索端口：返回候选 + 许可元数据。"""

    async def search(self, *, query: str, limit: int = 4) -> list[ImageCandidate]: ...


@runtime_checkable
class AssetRepositoryPort(Protocol):
    """资产元数据与缓存查询端口（`assets` 表）。

    `find_by_dedup_key` 按 org 作用域查已生成/已缓存资产，命中即跳过付费调用。
    """

    async def save(self, record: AssetRecord) -> AssetRecord: ...

    async def get_by_id(self, asset_id: uuid.UUID) -> AssetRecord | None: ...

    async def find_by_dedup_key(
        self, *, org_id: uuid.UUID, dedup_key: str
    ) -> AssetRecord | None: ...


@runtime_checkable
class MediaMeterPort(Protocol):
    """媒体计量端口（best-effort，仿 `UsageRecorder`）；失败不得阻断主流程。"""

    async def record(self, usage: MediaUsage) -> None: ...


@runtime_checkable
class MediaQuotaPort(Protocol):
    """付费调用前的配额闸（ADR-0005 §12）：check + consume，与计量分离。"""

    async def check(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> bool: ...

    async def consume(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> None: ...


def build_dedup_key(
    *,
    org_id: uuid.UUID,
    subject_key: str,
    description_summary: str,
    style: str,
    provider_version: str,
) -> str:
    """生成去重键（ADR-0005 §6）：按 org 作用域，避免跨 org 越权复用。

    `subject_key` 为场景 key（`scene:{scene_id}` / 运行期单调 key）或角色名；
    描述摘要做空白归一化后参与 hash。
    """

    summary = " ".join(description_summary.split())
    raw = "|".join(
        [str(org_id), subject_key.strip(), summary, style.strip(), provider_version.strip()]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SceneDesigner:
    """场景资产编排组件骨架（ADR-0005 §6）：检索→审核→回退生成→存储→AssetRef。

    M0 仅装配依赖；实际编排（幂等、缓存、付费前意图票据、审核回退）在 M2（#47）落地。
    依赖全部以端口注入，保证 domain 不触达基础设施。
    """

    def __init__(
        self,
        *,
        storage: ObjectStoragePort,
        image_gen: ImageGenPort,
        image_search: ImageSearchPort,
        assets: AssetRepositoryPort,
        meter: MediaMeterPort | None = None,
        quota: MediaQuotaPort | None = None,
    ) -> None:
        self.storage = storage
        self.image_gen = image_gen
        self.image_search = image_search
        self.assets = assets
        self.meter = meter
        self.quota = quota

    async def design_scene(
        self,
        *,
        org_id: uuid.UUID,
        subject_key: str,
        scene_key: str,
        description: str,
    ) -> AssetRecord:
        """编排单个场景/角色的背景资产（M2 #47 实现）。"""

        raise NotImplementedError("SceneDesigner 编排在 M2（#47）实现")


__all__ = [
    "AssetCredit",
    "AssetKind",
    "AssetRecord",
    "AssetRepositoryPort",
    "AssetSource",
    "AssetStatus",
    "GeneratedImage",
    "ImageCandidate",
    "ImageGenPort",
    "ImageSearchPort",
    "MediaKind",
    "MediaMeterPort",
    "MediaQuotaPort",
    "MediaUsage",
    "ObjectStoragePort",
    "SceneDesigner",
    "build_dedup_key",
]
