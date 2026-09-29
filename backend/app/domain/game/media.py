"""媒体端口与场景资产编排（ADR-0005 §2/§6，issue #39 M0 / #47 M2）。

本模块定义：

- **六个 domain 端口**（infra 提供适配器）：
  `ObjectStoragePort` / `ImageGenPort` / `ImageSearchPort` /
  `AssetRepositoryPort` / `MediaMeterPort` / `MediaQuotaPort`。
- 端口间传递的**领域数据结构**（不落契约，契约 `AssetRef`/`AssetCredit` 见 #43）。
- `SceneDesigner`：检索→审核→回退生成→存储→产出 `AssetRecord` 的编排组件（#47）。

分层约束：domain 不 import infrastructure；适配器在 `infrastructure/media/`。
转码（Pillow）与审核（LLM）都**不**在本模块里实现——转码以 `transcode` 可调用注入
（组合根传 `ImageProcessor().process`），审核以 `ImageReviewerPort` 注入（`#45` 的
`ImageReviewAgent`）。这样 domain 既守住了分层，又不必为「可能出现第二个转码后端」
提前造端口。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from app.contracts.script import AssetRef
from app.domain.game.media_safety import MAX_PROMPT_CHARS
from app.infrastructure.errx import Error

# 仅为类型标注：image_review 反向 import 本模块，运行期 import 会成环。
if TYPE_CHECKING:
    from app.domain.game.image_review import ImageReviewerPort

logger = logging.getLogger(__name__)


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


# 生成尺寸（ADR-0005 §6）：背景统一 16:9、头像 1:1（每角色一次、跨场景复用），
# 立绘走竖版。调用方未显式给宽高（0）时按 kind 取此表。
ASSET_SIZES: dict[AssetKind, tuple[int, int]] = {
    AssetKind.BACKGROUND: (1280, 720),
    AssetKind.AVATAR: (512, 512),
    AssetKind.FULLBODY: (768, 1024),
}


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
    """开放版权库检索的单条候选：字节 + 许可元数据 + 供审核的相关性文本。"""

    image_bytes: bytes
    content_type: str = "image/jpeg"
    source_url: str = ""
    width: int = 0
    height: int = 0
    # 图库标题/描述（审核 agent #45 判"相关"的文本依据；无视觉模型时唯一线索）。
    title: str = ""
    description: str = ""
    credit: AssetCredit = field(default_factory=AssetCredit)


@dataclass(frozen=True)
class GeneratedImage:
    """文生图结果。"""

    image_bytes: bytes
    content_type: str = "image/png"
    width: int = 0
    height: int = 0


@dataclass(frozen=True)
class Rendition:
    """转码产出的单个规格（ADR-0005 §4）：thumb/medium/original × webp/avif。

    这是 `domain` 消费的形状；转码实现（Pillow）在 infra，由组合根以
    `transcode=ImageProcessor().process` 注入——domain 不 import 基础设施，
    也不必为「第二个转码后端」提前造端口（ADR-0005 §2）。
    """

    name: str
    data: bytes
    content_type: str
    width: int = 0
    height: int = 0


# 转码函数：原图字节 → 多规格。抛 `MEDIA_IMAGE_INVALID` 表示字节不可处理。
TranscodeFn = Callable[[bytes], Sequence[Rendition]]


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
        self,
        *,
        org_id: uuid.UUID,
        dedup_key: str,
        status: AssetStatus | None = None,
    ) -> AssetRecord | None: ...


@runtime_checkable
class MediaMeterPort(Protocol):
    """媒体计量端口（best-effort，仿 `UsageRecorder`）；失败不得阻断主流程。"""

    async def record(self, usage: MediaUsage) -> None: ...


@runtime_checkable
class MediaQuotaPort(Protocol):
    """付费调用前的配额闸（ADR-0005 §12），与计量严格分离。

    **付费调用方必须用 `try_acquire`**：它在同一把锁内完成 seed + check + 预扣，
    并发不会超额；`check` + `consume` 是两步，N 个协程可同时通过 check 而一起付费
    （Stage2 并发生成多个场景、同 org 多个学生同时触发都会踩到）。
    """

    async def try_acquire(
        self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1
    ) -> bool: ...

    async def check(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> bool: ...

    async def consume(self, *, org_id: uuid.UUID, kind: MediaKind, units: int = 1) -> None: ...


def content_hash(data: bytes) -> str:
    """字节内容哈希（sha256 hex）：缓存排除集比对与 `assets.content_hash` 共用。"""
    return hashlib.sha256(data).hexdigest()


def build_dedup_key(
    *,
    org_id: uuid.UUID,
    subject_key: str,
    description_summary: str,
    style: str,
    provider_version: str,
    kind: AssetKind | str = "",
    scope: str = "",
) -> str:
    """生成去重键（ADR-0005 §5/§6）：org 作用域 + 归属作用域，避免越权复用。

    `subject_key` 为场景 key（`scene:{scene_id}` / 运行期单调 key）或角色名；
    描述摘要做空白归一化后参与 hash。

    `kind`（ADR §5 的 `purpose`）与 `scope`（`script:{id}` / `session:{id}`）**必须**参与，
    否则会踩两个坑：
    - 同一角色的 AVATAR 与 FULLBODY 描述往往只差几个字，键相同 → 立绘位复用 1:1 头像；
    - 跨剧本/会话同键复用会把**别人**的 `script_id`/`session_id` 带回，而
      `AssetAccessService` 按这两个字段鉴权 → 拿 URL 直接 403。

    代价是缓存不再跨剧本共享（同一课文的两位教师各付一次）；这是 ADR §5 把 `script_id`
    写进幂等键的既定取舍，成本优化留给后续立项。
    """

    kind_part = kind.value if isinstance(kind, AssetKind) else str(kind)
    summary = " ".join(description_summary.split())
    raw = "|".join(
        [
            str(org_id),
            subject_key.strip(),
            kind_part.strip(),
            scope.strip(),
            summary,
            style.strip(),
            provider_version.strip(),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# 生成 prompt 的统一画风/构图约束（ADR-0005 §6：背景不含人物、统一画风）。
DEFAULT_STYLE = "写实"
# 每个 kind 的构图尾巴。FULLBODY **不能**套背景那条——否则立绘会被要求
# 「画面中不出现任何人物」，永远生成不出角色（#47 评审发现）。
_KIND_TAILS: dict[AssetKind, str] = {
    AssetKind.BACKGROUND: "环境插画，画面中不出现任何人物，无文字无 logo",
    AssetKind.AVATAR: "角色头像，半身正面，纯色简洁背景，无文字无 logo",
    AssetKind.FULLBODY: "角色全身立绘，直立全身，简洁背景，无文字无 logo",
}
_DEFAULT_SEARCH_LIMIT = 4


def build_generation_prompt(
    *,
    description: str,
    kind: AssetKind,
    style: str = DEFAULT_STYLE,
    max_chars: int = MAX_PROMPT_CHARS,
) -> str:
    """场景/角色描述 → 文生图 prompt（按 kind 取构图约束，并收敛到长度预算内）。

    预算必须在这里守住：adapter 侧的 `screen_generation_prompt` 命中超长会抛**不可重试**
    的 `MEDIA_IMAGE_GEN_BLOCKED`，结果是该场景永远没有配图。Stage2 的场景描述由 beats
    拼接，长场景很容易超限，故超长时从描述尾部截断、**优先保构图与画风尾巴**。
    """
    subject = " ".join((description or "").split())
    tail = _KIND_TAILS.get(kind, _KIND_TAILS[AssetKind.BACKGROUND])
    suffix = "，".join(part for part in (f"{style}画风" if style else "", tail) if part)

    separator = "，" if subject and suffix else ""
    budget = max(1, max_chars - len(suffix) - len(separator))
    if len(subject) > budget:
        subject = subject[: max(0, budget - 1)].rstrip() + "…"
    return f"{subject}{separator}{suffix}"


@dataclass
class _Picked:
    """一次采纳的底图：字节 + 来源/署名/尺寸（检索采用与回退生成共用）。"""

    image_bytes: bytes
    content_type: str
    source: AssetSource
    provider: str = ""
    model: str = ""
    credit: AssetCredit = field(default_factory=AssetCredit)
    width: int = 0
    height: int = 0


class _UnusableCandidate(Exception):
    """候选字节不可用（截断/超像素/解码失败）：换下一个候选，而不是整次失败。"""


class SceneDesigner:
    """场景资产编排（ADR-0005 §6，issue #47）：检索→审核→回退生成→存储→AssetRecord。

    - **幂等与缓存**：`build_dedup_key` 按 (org, 归属作用域, 场景, kind, 风格, provider 版本)
      去重；命中 `READY` 资产直接复用，这是「不重复付费」的第一道闸。
    - **付费前意图票据**：付费调用之前先落 `assets` 行 `status=pending`
      （ADR-0005 §4 的固定顺序 pending → 上传对象 → ready），崩溃/重跑留下痕迹。
      在途任务的崩溃恢复（`asset_jobs` 重排）留待 #57。
    - **降级**：检索、审核、生成、转码、上传任一失败都**不抛给调用方**，而是返回
      `status=FAILED` 的记录，由上层（workflow #48 / 运行期 #56）以占位图或纯文本继续。
      DB 等非预期故障仍照常抛出（只有可预期的媒体失败才降级）。
    - 依赖全部端口注入；转码实现由组合根以 `transcode` 可调用注入（domain 不 import infra）。
    """

    def __init__(
        self,
        *,
        storage: ObjectStoragePort,
        image_gen: ImageGenPort,
        image_search: ImageSearchPort,
        assets: AssetRepositoryPort,
        reviewer: ImageReviewerPort,
        transcode: TranscodeFn,
        meter: MediaMeterPort | None = None,
        quota: MediaQuotaPort | None = None,
        style: str = DEFAULT_STYLE,
        provider_version: str = "",
        generation_model: str = "",
        search_limit: int = _DEFAULT_SEARCH_LIMIT,
    ) -> None:
        self.storage = storage
        self.image_gen = image_gen
        self.image_search = image_search
        self.assets = assets
        self.reviewer = reviewer
        self.transcode = transcode
        self.meter = meter
        self.quota = quota
        self.style = style
        self.generation_model = generation_model
        # 参与去重键：换 provider **或** model 等于换了产出，缓存必须失效。
        # 只取类名会漏掉「同一 adapter 换 model」（换画风/换厂商走兼容端点）的情形。
        self.provider_version = provider_version or (
            f"{type(image_gen).__name__}:{generation_model}".rstrip(":")
        )
        self.search_limit = search_limit

    async def design_scene(
        self,
        *,
        org_id: uuid.UUID,
        subject_key: str,
        scene_key: str,
        description: str,
        kind: AssetKind = AssetKind.BACKGROUND,
        style: str | None = None,
        provider_version: str = "",
        script_id: int | None = None,
        session_id: uuid.UUID | None = None,
        user_id: uuid.UUID | None = None,
        exclude_asset_ids: Sequence[uuid.UUID] = (),
        exclude_content_hashes: Sequence[str] = (),
        search_only: bool = False,
    ) -> AssetRecord:
        """为某个场景/角色产出资产记录（`READY` 可签发 URL；`FAILED` 由上层降级）。

        `exclude_asset_ids` / `exclude_content_hashes`（#49 教师重生成/检索替换）：
        把教师明确否掉的旧图排除在缓存命中与检索候选之外——同一去重键下教师
        「重新生成」要求换一张图；排除旧 id 后 `find_by_dedup_key`（取最新行）
        自然落到重生成产物，崩溃重放仍是幂等的。

        `search_only`（#49 检索替换）：只用开放版权检索，无采纳候选时直接 FAILED，
        不回退付费生成（教师明确要求检索来源时，替他生成一张是越权花钱）。
        """
        del scene_key  # 保留在签名里给审计/日志用；去重键由 subject_key 承担
        resolved_style = self.style if style is None else style
        dedup_key = build_dedup_key(
            org_id=org_id,
            subject_key=subject_key,
            description_summary=description,
            style=resolved_style,
            provider_version=provider_version or self.provider_version,
            kind=kind,
            scope=_ownership_scope(script_id=script_id, session_id=session_id),
        )

        cached = await self.assets.find_by_dedup_key(
            org_id=org_id, dedup_key=dedup_key, status=AssetStatus.READY
        )
        if cached is not None and cached.asset_id not in exclude_asset_ids:
            logger.info(
                "scene_asset_cache_hit subject=%s asset=%s", subject_key, cached.asset_id
            )
            return cached

        record = await self._new_ticket(
            org_id=org_id,
            kind=kind,
            dedup_key=dedup_key,
            script_id=script_id,
            source=AssetSource.GENERATED,
            provider="",
        )

        # 教师重生成/检索替换（#49）：调用方只有稳定引用（AssetRef），拿不到
        # 内容哈希——在这里按 id 反查补齐，检索候选的排除集才完整。
        hash_exclusions = set(exclude_content_hashes)
        for old_id in exclude_asset_ids:
            old = await self.assets.get_by_id(old_id)
            if old is not None and old.content_hash:
                hash_exclusions.add(old.content_hash)


        # 免费侧：逐个试已被审核采纳的候选。候选字节可能不可解码（图库截断/超像素），
        # 那个候选不采用、继续下一个，而不是让整次编排以 FAILED 收场。
        async for picked in self._accepted_candidates(
            description=description,
            kind=kind,
            exclude_content_hashes=hash_exclusions,
        ):
            try:
                return await self._publish(
                    record, picked, org_id=org_id, user_id=user_id
                )
            except _UnusableCandidate as exc:
                logger.info(
                    "scene_asset_candidate_unusable asset=%s reason=%s",
                    record.asset_id,
                    exc,
                )

        picked = (
            await self._generate(
                org_id=org_id,
                description=description,
                kind=kind,
                style=resolved_style,
                exclude_content_hashes=hash_exclusions,
            )
            if not search_only
            else None
        )
        if picked is None:
            return await self._fail(record, reason="no usable image (search+review+generate)")
        # 钱**已经花了**：计量必须在此刻落，不能等到 READY——否则转码/上传失败时
        # 这笔真实花费在记账与配额种子里完全消失（ADR-0005 §12）。
        await self._meter(
            picked,
            org_id=org_id,
            user_id=user_id,
            script_id=script_id,
            session_id=session_id,
        )
        try:
            return await self._publish(record, picked, org_id=org_id, user_id=user_id)
        except _UnusableCandidate as exc:
            return await self._fail(record, reason=f"generated image unusable: {exc}")

    # ===== 免费侧：检索 → 审核 =====

    async def _accepted_candidates(
        self,
        *,
        description: str,
        kind: AssetKind,
        exclude_content_hashes: Sequence[str] = (),
    ) -> AsyncIterator[_Picked]:
        """产出被审核采纳的候选；审核链路本身挂掉时立即收束（别再逐条白问）。"""
        try:
            candidates = await self.image_search.search(
                query=description, limit=self.search_limit
            )
        except Error as exc:
            # 检索不可用只意味着「少一条免费路径」，不阻断回退生成。
            logger.info("scene_asset_search_unavailable reason=%s", exc.msg)
            return

        excluded = set(exclude_content_hashes)
        for candidate in candidates:
            if excluded and self._content_hash(candidate) in excluded:
                # 教师重生成/检索替换（#49）：旧图字节原样回来了不算「换了一张」。
                logger.info(
                    "scene_asset_candidate_excluded source=%s", candidate.source_url
                )
                continue
            verdict = await self.reviewer.review(
                candidate, scene_description=description, kind=kind
            )
            if verdict.accepted:
                yield _Picked(
                    image_bytes=candidate.image_bytes,
                    content_type=candidate.content_type,
                    source=AssetSource.SEARCH,
                    provider="image_search",
                    credit=candidate.credit,
                    width=candidate.width,
                    height=candidate.height,
                )
                continue
            if verdict.degraded:
                # REVIEW_FAILED 表示审核通道本身故障（超时/无 key）。再问剩下的候选
                # 只会重复付费式往返，直接转付费回退生成。
                logger.warning(
                    "scene_asset_review_degraded kind=%s -> fallback generate", kind.value
                )
                return
            logger.info(
                "scene_asset_candidate_rejected reason=%s source=%s",
                getattr(verdict.reason, "value", verdict.reason),
                candidate.source_url,
            )

    # ===== 付费侧：原子配额闸 → 生成 → 计量 =====

    async def _generate(
        self,
        *,
        org_id: uuid.UUID,
        description: str,
        kind: AssetKind,
        style: str,
        exclude_content_hashes: Sequence[str] = (),
    ) -> _Picked | None:
        """付费回退生成。

        `exclude_content_hashes`（#49）语义：文生图无法保证「与旧图不同」——同
        prompt 同模型完全可能产出相近图。这里的防线是**生成后比对**：命中排除集
        视为本次编排失败（返回 None → 上层记 FAILED），由教师再次重试；不悄悄
        放行旧字节，也不为换图无限重烧配额。
        """
        # 原子预扣：check+consume 两步在并发下会双双通过而超额（quota.py 明确要求
        # 付费方走 try_acquire）。
        if self.quota is not None and not await self.quota.try_acquire(
            org_id=org_id, kind=MediaKind.IMAGE
        ):
            logger.warning("scene_asset_quota_exhausted org=%s", org_id)
            return None

        prompt = build_generation_prompt(description=description, kind=kind, style=style)
        try:
            image = await self.image_gen.generate(prompt=prompt, kind=kind)
        except Error as exc:
            logger.warning("scene_asset_generation_failed reason=%s", exc.msg)
            return None
        if not image.image_bytes:
            logger.warning("scene_asset_generation_empty prompt=%r", prompt[:80])
            return None
        if (
            exclude_content_hashes
            and content_hash(image.image_bytes) in set(exclude_content_hashes)
        ):
            logger.warning(
                "scene_asset_generation_duplicate subject_desc=%r", description[:60]
            )
            return None

        return _Picked(
            image_bytes=image.image_bytes,
            content_type=image.content_type,
            source=AssetSource.GENERATED,
            provider=type(self.image_gen).__name__,
            model=self.generation_model,
            width=image.width,
            height=image.height,
        )

    # ===== 存储与收尾 =====

    async def _publish(
        self, record: AssetRecord, picked: _Picked, *, org_id: uuid.UUID, user_id: uuid.UUID | None
    ) -> AssetRecord:
        try:
            # 转码是同步 CPU 密集（最多 6 次编码、40M 像素上限）；单 worker 部署下
            # 直接调用会卡住事件循环，WS 字幕与 HTTP 一起停顿。移出到线程。
            renditions = list(await asyncio.to_thread(self.transcode, picked.image_bytes))
        except Error as exc:
            raise _UnusableCandidate(f"transcode: {exc.msg}") from exc
        except Exception as exc:  # noqa: BLE001 - 实现在超预算内存下会抛 MemoryError 等
            # 非 Error 异常不能穿透：上层只做占位降级，穿透会变成 500。
            raise _UnusableCandidate(f"transcode crashed: {exc}") from exc
        if not renditions:
            raise _UnusableCandidate("transcode produced no rendition")

        for rendition in renditions:
            key = _rendition_key(org_id, record.asset_id, rendition.name)
            try:
                await self.storage.put(
                    object_key=key, data=rendition.data, content_type=rendition.content_type
                )
            except Error as exc:
                # 上传失败是基础设施问题，换候选也无济于事。
                return await self._fail(record, reason=f"upload {rendition.name}: {exc.msg}")

        primary = _primary_rendition(renditions)
        record.object_key = _rendition_key(org_id, record.asset_id, primary.name)
        record.status = AssetStatus.READY
        record.source = picked.source
        record.provider = picked.provider
        record.model = picked.model
        record.credit = picked.credit
        record.width = picked.width or primary.width
        record.height = picked.height or primary.height
        record.content_hash = content_hash(picked.image_bytes)
        await self.assets.save(record)
        if picked.source is AssetSource.SEARCH:
            # 免费来源：补一条溯源计量，但 units=0 —— 否则会把 org 的**付费**预算白吃
            # （MediaQuotaService 对 (org, kind=image) 求和，不区分 provider）。
            await self._meter(
                picked,
                org_id=org_id,
                user_id=user_id,
                script_id=record.script_id,
                session_id=record.session_id,
                units=0,
            )
        logger.info(
            "scene_asset_ready asset=%s source=%s renditions=%d",
            record.asset_id,
            record.source.value,
            len(renditions),
        )
        return record

    async def _fail(self, record: AssetRecord, *, reason: str) -> AssetRecord:
        """失败也落库（`FAILED`），让上层能区分「还没好」与「不会好」。"""
        logger.warning("scene_asset_failed asset=%s reason=%s", record.asset_id, reason)
        record.status = AssetStatus.FAILED
        await self.assets.save(record)
        return record

    async def _new_ticket(
        self,
        *,
        org_id: uuid.UUID,
        kind: AssetKind,
        dedup_key: str,
        script_id: int | None,
        source: AssetSource,
        provider: str,
        session_id: uuid.UUID | None = None,
    ) -> AssetRecord:
        """付费/发布前先落 `PENDING` 票据（ADR-0005 §4 固定顺序），崩溃留痕。"""
        asset_id = uuid.uuid4()
        record = AssetRecord(
            asset_id=asset_id,
            object_key=_rendition_key(org_id, asset_id, "original.webp"),
            kind=kind,
            status=AssetStatus.PENDING,
            source=source,
            provider=provider,
            org_id=org_id,
            script_id=script_id,
            session_id=session_id,
            dedup_key=dedup_key,
        )
        await self.assets.save(record)
        return record

    async def publish_upload(
        self,
        *,
        org_id: uuid.UUID,
        subject_key: str,
        scene_key: str,
        description: str,
        kind: AssetKind,
        image_bytes: bytes,
        content_type: str = "image/png",
        script_id: int | None = None,
        user_id: uuid.UUID | None = None,
    ) -> AssetRecord:
        """教师自有素材上传（#49）：复用转码/多规格/落库管线，不计费、不走审核。

        - `AssetSource.UPLOADED`：来源标记供署名合规（教师上传需审核的内容
          责任在教师侧，ADR-0005 §6）与 #51 来源展示区分；
        - 编排契约与其他来源一致：失败**不抛**，返回 `FAILED` 记录（转码不可
          解码等）。上传是教师同步操作，调用方（服务层）须检查 status 并把
          FAILED 转成即时错误反馈，不能像 workflow 那样静默降级；
        - 去重键与生成同构（同 subject 同文件命中缓存，防重复占存储）。
        """
        dedup_key = build_dedup_key(
            org_id=org_id,
            subject_key=subject_key,
            description_summary=description,
            style="upload",
            provider_version="teacher_upload",
            kind=kind,
            scope=_ownership_scope(script_id=script_id, session_id=None),
        )
        record = await self._new_ticket(
            org_id=org_id,
            kind=kind,
            dedup_key=dedup_key,
            script_id=script_id,
            source=AssetSource.UPLOADED,
            provider="teacher_upload",
        )
        cached = await self.assets.find_by_dedup_key(
            org_id=org_id, dedup_key=dedup_key, status=AssetStatus.READY
        )
        if cached is not None:
            logger.info(
                "scene_asset_upload_cache_hit subject=%s asset=%s",
                subject_key,
                cached.asset_id,
            )
            return cached

        picked = _Picked(
            image_bytes=image_bytes,
            content_type=content_type,
            source=AssetSource.UPLOADED,
            provider="teacher_upload",
        )
        try:
            return await self._publish(record, picked, org_id=org_id, user_id=user_id)
        except _UnusableCandidate as exc:
            return await self._fail(record, reason=f"teacher upload unusable: {exc}")

    @staticmethod
    def _content_hash(candidate: ImageCandidate) -> str:
        """检索候选的字节哈希（#49 排除集比对）。"""
        return content_hash(candidate.image_bytes)

    async def find_bindable_upload(
        self, *, asset_id: uuid.UUID, org_id: uuid.UUID, kind: AssetKind
    ) -> AssetRecord | None:
        """校验并取出可绑定的教师上传件（#49 bind_upload）。

        绑定前必须确认三件事，缺一不可（防越权/防错位绑定）：
        - 资产存在且 `status=READY`；
        - 归属同一 org（上传端点按剧本归属落库，org 匹配即同一租户）；
        - `source=UPLOADED` 且 kind 与槽位一致——生成/检索件走各自的
          设计/替换语义，不允许经 bind_upload 冒充上传。
        """
        record = await self.assets.get_by_id(asset_id)
        if (
            record is None
            or record.status is not AssetStatus.READY
            or record.org_id != org_id
            or record.source is not AssetSource.UPLOADED
            or record.kind is not kind
        ):
            return None
        return record

    async def _meter(
        self,
        picked: _Picked,
        *,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None,
        script_id: int | None,
        session_id: uuid.UUID | None,
        units: int = 1,
    ) -> None:
        """计量 best-effort（ADR-0005 §12）：失败不得影响已成功的产出。"""
        if self.meter is None:
            return
        try:
            await self.meter.record(
                MediaUsage(
                    kind=MediaKind.IMAGE,
                    provider=picked.provider,
                    model=picked.model,
                    units=units,
                    size=len(picked.image_bytes),
                    org_id=org_id,
                    user_id=user_id,
                    script_id=script_id,
                    session_id=session_id,
                    meta={"source": picked.source.value},
                )
            )
        except Exception as exc:  # noqa: BLE001 - 计量是旁路，不能反噬主流程
            logger.warning("scene_asset_meter_failed reason=%s", exc)


def to_asset_ref(record: AssetRecord) -> AssetRef:
    """`AssetRecord` → 契约稳定引用（ADR-0005 §3）：只出 id/kind/status。

    `object_key` 与字节都不进契约；URL 由鉴权端点按 asset_id 签发（#42）。
    #48 组装 `ScriptPackage` 时用它填 `Scene.background_asset`。
    """
    return AssetRef(
        asset_id=record.asset_id,
        kind=record.kind.value,
        status=record.status.value,
    )


def _ownership_scope(*, script_id: int | None, session_id: uuid.UUID | None) -> str:
    """归属作用域：生成期按剧本、运行期按会话（ADR-0005 §5 的幂等键含 script_id）。"""
    if script_id is not None:
        return f"script:{script_id}"
    if session_id is not None:
        return f"session:{session_id}"
    return ""


def _rendition_key(org_id: uuid.UUID, asset_id: uuid.UUID, name: str) -> str:
    """对象键：`{org}/assets/{asset_id}/{规格}`。字节与键都不进契约（ADR-0005 §3）。

    各档共用同一目录前缀，因此「按 asset_id + 规格名推导」即可寻址到 thumb/medium
    （端点支持 variant 参数前，其余规格只是先按 ADR §4 落库）。
    """
    return f"{org_id}/assets/{asset_id}/{name}"


def _primary_rendition(renditions: Sequence[Rendition]) -> Rendition:
    """`assets.object_key` 指向哪一档：优先 original，同档优先 webp（浏览器通用）。"""
    originals = [r for r in renditions if r.name.startswith("original")]
    pool = originals or list(renditions)
    webp = [r for r in pool if r.content_type == "image/webp"]
    return (webp or pool)[0]
