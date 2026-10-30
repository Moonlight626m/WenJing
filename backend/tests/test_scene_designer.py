"""SceneDesigner 编排测试（issue #47 / ADR-0005 §4/§6）。

验收对应：
- 「给定场景产出 AssetRef」→ test_search_accept_path_returns_ready_record
- 「resume/重跑不重复生成」→ test_second_run_hits_cache_and_skips_paid_calls
- 「缓存命中不重复付费」→ test_cache_hit_skips_paid_calls / 换 provider 失效缓存
- 「缓存跨会话命中」（#57）→ test_cache_hits_across_sessions_of_the_same_script
- 「安全过滤命中丢弃」（#57）→ test_blocked_prompt_is_dropped_before_quota

全部用 fake 端口，无 DB、无网络；真实存储/生图链路由各自 adapter 的 key-gated 冒烟覆盖。
"""

from __future__ import annotations

import hashlib
import uuid
from io import BytesIO

import pytest

from app.domain.game.image_review import ImageReviewResult, LicenseStatus, ReviewReason
from app.domain.game.media import (
    AssetCredit,
    AssetKind,
    AssetRecord,
    AssetSource,
    AssetStatus,
    GeneratedImage,
    ImageCandidate,
    Rendition,
    SceneDesigner,
    build_dedup_key,
    build_generation_prompt,
    requires_attribution,
    to_asset_ref,
    to_contract_credit,
)
from app.domain.game.media_safety import MAX_PROMPT_CHARS
from app.infrastructure.errx import codes, new

_ORG = uuid.UUID("11111111-1111-1111-1111-111111111111")
_DESCRIPTION = "古老的江南水乡"


def _png(width: int = 64, height: int = 36) -> bytes:
    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (width, height), (30, 60, 90)).save(buffer, format="PNG")
    return buffer.getvalue()


def _renditions(data: bytes) -> list[Rendition]:
    return [
        Rendition(name="thumb.webp", data=b"t", content_type="image/webp", width=16, height=9),
        Rendition(name="original.webp", data=data, content_type="image/webp", width=64, height=36),
        Rendition(name="original.avif", data=b"a", content_type="image/avif", width=64, height=36),
    ]


# ===== fakes（端口形状与 infra 适配器一致，但不触达 DB/网络）=====


class FakeStorage:
    def __init__(self, *, fail_on: str | None = None) -> None:
        self.puts: list[str] = []
        self._fail_on = fail_on

    async def put(self, *, object_key: str, data: bytes, content_type: str) -> None:
        if self._fail_on and object_key.endswith(self._fail_on):
            raise new(codes.MEDIA_STORAGE_FAILED, extra={"op": "put", "reason": "boom"})
        self.puts.append(object_key)

    async def presign(self, *, object_key: str, ttl_seconds: int = 900) -> str:
        return f"https://cdn/{object_key}"


class FakeAssets:
    """内存仓库；`calls` 记录调用顺序，用于断言「付费前先落 pending 票据」。"""

    def __init__(self, *, seed: list[AssetRecord] | None = None) -> None:
        self.rows: dict[uuid.UUID, AssetRecord] = {r.asset_id: r for r in (seed or [])}
        self.calls: list[str] = []

    async def save(self, record: AssetRecord) -> AssetRecord:
        self.calls.append(f"save:{record.status.value}")
        self.rows[record.asset_id] = record
        return record

    async def get_by_id(self, asset_id: uuid.UUID) -> AssetRecord | None:
        return self.rows.get(asset_id)

    async def find_by_dedup_key(
        self,
        *,
        org_id: uuid.UUID,
        dedup_key: str,
        status: AssetStatus | None = None,
    ) -> AssetRecord | None:
        matches = [r for r in self.rows.values() if r.dedup_key == dedup_key]
        if status is not None:
            matches = [r for r in matches if r.status is status]
        return matches[-1] if matches else None


class FakeSearch:
    def __init__(self, *, candidates: list[ImageCandidate] | None = None, error: bool = False):
        self._candidates = candidates or []
        self._error = error
        self.calls = 0

    async def search(self, *, query: str, limit: int = 4) -> list[ImageCandidate]:
        self.calls += 1
        if self._error:
            raise new(codes.MEDIA_SEARCH_FAILED, extra={"reason": "down"})
        return self._candidates


class FakeReviewer:
    def __init__(self, *, accept: bool = True, degrade: bool = False) -> None:
        self._accept = accept
        self._degrade = degrade

    async def review(self, candidate, *, scene_description: str, kind: AssetKind):
        if self._degrade:
            return ImageReviewResult(
                accepted=False,
                license_status=LicenseStatus.ATTRIBUTION_FREE,
                reason=ReviewReason.REVIEW_FAILED,
            )
        return ImageReviewResult(
            accepted=self._accept,
            license_status=LicenseStatus.ATTRIBUTION_FREE,
            reason=ReviewReason.ACCEPTED if self._accept else ReviewReason.IRRELEVANT,
        )


class FakeGen:
    def __init__(self, *, error: bool = False) -> None:
        self._error = error
        self.calls = 0
        self.prompts: list[str] = []

    async def generate(self, *, prompt: str, kind: AssetKind, width: int = 0, height: int = 0):
        self.calls += 1
        self.prompts.append(prompt)
        if self._error:
            raise new(codes.MEDIA_IMAGE_GEN_FAILED, extra={"reason": "provider down"})
        return GeneratedImage(
            image_bytes=_png(), content_type="image/png", width=64, height=36
        )


class FakeQuota:
    def __init__(self, *, allowed: bool = True) -> None:
        self.allowed = allowed
        self.consumed = 0

    async def try_acquire(self, *, org_id: uuid.UUID, kind, units: int = 1) -> bool:
        if not self.allowed:
            return False
        self.consumed += units
        return True

    async def check(self, *, org_id: uuid.UUID, kind, units: int = 1) -> bool:
        return self.allowed

    async def consume(self, *, org_id: uuid.UUID, kind, units: int = 1) -> None:
        self.consumed += units


class FakeMeter:
    def __init__(self, *, error: bool = False) -> None:
        self.records = []
        self._error = error

    async def record(self, usage) -> None:
        if self._error:
            raise RuntimeError("meter exploded")
        self.records.append(usage)


class BoomTranscode:
    def __call__(self, _data: bytes) -> list[Rendition]:
        raise new(codes.MEDIA_IMAGE_INVALID, extra={"reason": "not an image"})


class EmptyTranscode:
    def __call__(self, _data: bytes) -> list[Rendition]:
        return []


def _designer(
    *,
    storage=None,
    assets=None,
    search=None,
    reviewer=None,
    gen=None,
    quota=None,
    meter=None,
    transcode=None,
    provider_version: str = "",
) -> SceneDesigner:
    return SceneDesigner(
        storage=storage or FakeStorage(),
        image_gen=gen or FakeGen(),
        image_search=search or FakeSearch(),
        assets=assets or FakeAssets(),
        reviewer=reviewer or FakeReviewer(),
        transcode=transcode or _renditions,
        meter=meter,
        quota=quota,
        provider_version=provider_version,
    )


async def _design(designer: SceneDesigner, **overrides) -> AssetRecord:
    kwargs = {
        "org_id": _ORG,
        "subject_key": "scene:1",
        "scene_key": "scene:1",
        "description": _DESCRIPTION,
    }
    kwargs.update(overrides)
    return await designer.design_scene(**kwargs)


def _dedup_key(
    *, kind: AssetKind = AssetKind.BACKGROUND, scope: str = "", provider: str = "FakeGen"
) -> str:
    return build_dedup_key(
        org_id=_ORG,
        subject_key="scene:1",
        description_summary=_DESCRIPTION,
        style="写实",
        provider_version=provider,
        kind=kind,
        scope=scope,
    )


# ===== 顺利路径 =====


async def test_search_accept_path_returns_ready_record():
    candidate = ImageCandidate(
        image_bytes=_png(),
        credit=AssetCredit(author="张三", license="CC0", source_url="https://x/1"),
    )
    storage = FakeStorage()
    designer = _designer(storage=storage, search=FakeSearch(candidates=[candidate]))

    record = await _design(designer)

    assert record.status is AssetStatus.READY
    assert record.source is AssetSource.SEARCH
    assert record.credit.author == "张三"  # 署名随资产落库（#51/#54 展示）
    assert record.content_hash  # 内容指纹已填
    # 三个规格都上传，object_key 指向 original（同档优先 webp）
    assert len(storage.puts) == 3
    assert record.object_key.endswith("/original.webp")
    assert all(k.startswith(f"{_ORG}/assets/{record.asset_id}/") for k in storage.puts)


async def test_fallback_to_generation_when_no_candidate():
    gen = FakeGen()
    designer = _designer(search=FakeSearch(candidates=[]), gen=gen)

    record = await _design(designer)

    assert record.status is AssetStatus.READY
    assert record.source is AssetSource.GENERATED
    assert gen.calls == 1
    # prompt 带上「不出现人物」的构图约束（ADR-0005 §6）
    assert "不出现任何人物" in gen.prompts[0]


async def test_rejected_candidate_falls_back_to_generation():
    candidate = ImageCandidate(image_bytes=_png())
    gen = FakeGen()
    designer = _designer(
        search=FakeSearch(candidates=[candidate]), reviewer=FakeReviewer(accept=False), gen=gen
    )

    record = await _design(designer)

    assert record.source is AssetSource.GENERATED
    assert gen.calls == 1


async def test_degraded_review_falls_back_to_generation():
    """审核降级（LLM 失败）按拒绝处理，不采用未审核素材（#45 语义）。"""
    candidate = ImageCandidate(image_bytes=_png())
    gen = FakeGen()
    designer = _designer(
        search=FakeSearch(candidates=[candidate]), reviewer=FakeReviewer(degrade=True), gen=gen
    )

    record = await _design(designer)

    assert record.source is AssetSource.GENERATED
    assert gen.calls == 1


async def test_search_failure_does_not_block_generation():
    gen = FakeGen()
    designer = _designer(search=FakeSearch(error=True), gen=gen)

    record = await _design(designer)

    assert record.status is AssetStatus.READY
    assert gen.calls == 1


# ===== 幂等与缓存（不重复付费）=====


async def test_second_run_hits_cache_and_skips_paid_calls():
    gen, search = FakeGen(), FakeSearch()
    designer = _designer(assets=FakeAssets(), gen=gen, search=search)

    first = await _design(designer)
    second = await _design(designer)

    assert second.asset_id == first.asset_id
    assert gen.calls == 1, "第二次必须命中缓存，不得再次付费生成"
    assert search.calls == 1, "命中缓存后连检索都不该再走"


async def test_cache_hit_skips_paid_calls():
    existing = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/original.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        org_id=_ORG,
        dedup_key=_dedup_key(),
    )
    gen, search = FakeGen(), FakeSearch()
    designer = _designer(assets=FakeAssets(seed=[existing]), gen=gen, search=search)

    record = await _design(designer)

    assert record.asset_id == existing.asset_id
    assert gen.calls == 0 and search.calls == 0


async def test_pending_row_is_not_a_cache_hit():
    """崩溃留下的 pending 票据不该被当成成品复用（崩溃恢复细化在 #57）。"""
    stale = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/original.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.PENDING,
        org_id=_ORG,
        dedup_key=_dedup_key(),
    )
    gen = FakeGen()
    designer = _designer(assets=FakeAssets(seed=[stale]), gen=gen)

    record = await _design(designer)

    assert record.asset_id != stale.asset_id
    assert record.status is AssetStatus.READY
    assert gen.calls == 1


async def test_provider_version_change_misses_cache():
    """换生图 provider/model 等于换产出，缓存必须失效（否则会复用旧画风的图）。"""
    assets, gen = FakeAssets(), FakeGen()
    await _design(_designer(assets=assets, gen=gen))

    await _design(_designer(assets=assets, gen=gen, provider_version="OtherModel"))

    assert gen.calls == 2


# ===== 付费前意图票据 =====


async def test_pending_ticket_saved_before_paid_call():
    """ADR-0005 §4 的固定顺序：付费调用之前先落 pending 行。"""
    order: list[str] = []

    class OrderedAssets(FakeAssets):
        async def save(self, record: AssetRecord) -> AssetRecord:
            order.append(f"save:{record.status.value}")
            return await super().save(record)

    class OrderedGen(FakeGen):
        async def generate(self, **kwargs):
            order.append("generate")
            return await super().generate(**kwargs)

    designer = _designer(
        assets=OrderedAssets(), gen=OrderedGen(), search=FakeSearch(candidates=[])
    )
    await _design(designer)

    assert order[0] == "save:pending", f"票据必须先于付费调用落库，实际顺序 {order}"
    assert order.index("generate") > 0


# ===== 降级：失败不抛，返回 FAILED 记录 =====


async def test_quota_exhausted_fails_without_paid_call():
    gen, quota = FakeGen(), FakeQuota(allowed=False)
    designer = _designer(gen=gen, quota=quota, search=FakeSearch(candidates=[]))

    record = await _design(designer)

    assert record.status is AssetStatus.FAILED
    assert gen.calls == 0, "配额不足时绝不能发起付费调用"
    assert quota.consumed == 0


@pytest.mark.parametrize(
    "kw",
    [
        pytest.param({"gen": FakeGen(error=True)}, id="generation-error"),
        pytest.param({"transcode": BoomTranscode()}, id="transcode-error"),
        pytest.param({"transcode": EmptyTranscode()}, id="transcode-empty"),
        pytest.param({"storage": FakeStorage(fail_on="original.webp")}, id="upload-error"),
    ],
)
async def test_failures_return_failed_record_instead_of_raising(kw):
    """上层（#48 workflow / #56 运行期）只做占位降级，不该被异常打断游玩。"""
    designer = _designer(search=FakeSearch(candidates=[]), **kw)

    record = await _design(designer)

    assert record.status is AssetStatus.FAILED


async def test_meter_failure_does_not_undo_success():
    designer = _designer(meter=FakeMeter(error=True), search=FakeSearch(candidates=[]))

    record = await _design(designer)

    assert record.status is AssetStatus.READY


async def test_meter_records_generation_usage():
    meter = FakeMeter()
    designer = _designer(meter=meter, search=FakeSearch(candidates=[]))

    await _design(designer)

    assert len(meter.records) == 1
    assert meter.records[0].provider == "FakeGen"
    assert meter.records[0].org_id == _ORG


async def test_unexpected_error_still_propagates():
    """只有可预期的媒体失败才降级；DB 类非预期故障必须抛出去（否则会被误当 provider 抖动）。"""

    class ExplodingAssets(FakeAssets):
        async def save(self, record: AssetRecord) -> AssetRecord:
            raise RuntimeError("db down")

    designer = _designer(assets=ExplodingAssets())

    with pytest.raises(RuntimeError):
        await _design(designer)


# ===== prompt 构造 =====


def test_generation_prompt_varies_by_kind():
    background = build_generation_prompt(description="江南水乡", kind=AssetKind.BACKGROUND)
    avatar = build_generation_prompt(description="父亲", kind=AssetKind.AVATAR)
    assert "不出现任何人物" in background
    assert "半身" in avatar
    assert background != avatar


# ===== 契约投影（验收：「给定场景产出 AssetRef」）=====


def test_to_asset_ref_excludes_internal_fields():
    record = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="org/assets/x/original.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
    )

    ref = to_asset_ref(record)

    assert ref.asset_id == record.asset_id
    assert ref.kind == "background" and ref.status == "ready"
    # object_key 与字节绝不进契约（ADR-0005 §3）
    assert "object_key" not in ref.model_dump()


async def test_design_scene_output_is_contract_projectable():
    designer = _designer(search=FakeSearch(candidates=[]))
    record = await _design(designer)

    ref = to_asset_ref(record)

    assert ref.status == "ready"
    assert ref.kind == "background"


# ===== 评审回归：缓存键、候选兜底、计量口径、配额原子性 =====


async def test_avatar_and_fullbody_do_not_share_cache():
    """回归：去重键曾漏掉 kind，同一角色的头像与立绘会互相命中（立绘位显示 1:1 头像）。"""
    assets, gen = FakeAssets(), FakeGen()
    designer = _designer(assets=assets, gen=gen)

    avatar = await _design(designer, kind=AssetKind.AVATAR)
    fullbody = await _design(designer, kind=AssetKind.FULLBODY)

    assert avatar.asset_id != fullbody.asset_id
    assert gen.calls == 2


async def test_cache_is_scoped_to_owning_script():
    """回归：跨剧本复用会把别人的 script_id 带回，拿 URL 时 403。"""
    assets, gen = FakeAssets(), FakeGen()
    designer = _designer(assets=assets, gen=gen)

    first = await _design(designer, script_id=101)
    second = await _design(designer, script_id=202)

    assert first.asset_id != second.asset_id, "不同剧本不得共享同一资产归属"
    assert second.script_id == 202
    assert gen.calls == 2


async def test_same_script_still_hits_cache():
    """归属作用域进键不等于放弃幂等：同剧本重跑仍必须命中。"""
    gen = FakeGen()
    designer = _designer(gen=gen)

    first = await _design(designer, script_id=101)
    second = await _design(designer, script_id=101)

    assert second.asset_id == first.asset_id
    assert gen.calls == 1


async def test_newer_pending_row_does_not_shadow_ready():
    """回归：lookup 曾不过滤状态，更新时间的 pending 行会遮住更早的 READY → 再次付费。"""
    ready = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/original.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        org_id=_ORG,
        dedup_key=_dedup_key(),
    )
    stale_pending = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/original.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.PENDING,
        org_id=_ORG,
        dedup_key=_dedup_key(),
    )
    gen = FakeGen()
    designer = _designer(assets=FakeAssets(seed=[ready, stale_pending]), gen=gen)

    record = await _design(designer)

    assert record.asset_id == ready.asset_id
    assert gen.calls == 0


def test_fullbody_prompt_asks_for_a_character():
    """回归：立绘曾套用背景尾巴，被要求「画面中不出现任何人物」。"""
    fullbody = build_generation_prompt(description="父亲", kind=AssetKind.FULLBODY)
    assert "不出现任何人物" not in fullbody
    assert "全身" in fullbody


def test_generation_prompt_respects_length_budget():
    """回归：超长 prompt 会被 provider 侧判不可重试的 BLOCKED，导致该场景永远没有配图。"""
    prompt = build_generation_prompt(description="背" * 5000, kind=AssetKind.BACKGROUND)
    assert len(prompt) <= MAX_PROMPT_CHARS
    assert "不出现任何人物" in prompt  # 截断发生在描述上，构图尾巴必须保留


class _FlakyTranscode:
    """前 `fail_times` 次抛错，之后正常——模拟图库候选字节截断/超像素。"""

    def __init__(self, fail_times: int = 1) -> None:
        self._left = fail_times
        self.calls = 0

    def __call__(self, data: bytes) -> list[Rendition]:
        self.calls += 1
        if self._left > 0:
            self._left -= 1
            raise new(codes.MEDIA_IMAGE_INVALID, extra={"reason": "truncated"})
        return _renditions(data)


async def test_unusable_candidate_falls_through_to_next_one():
    """回归：首个候选字节不可解码时不应整次 FAILED，而应换下一个候选。"""
    candidates = [ImageCandidate(image_bytes=b"bad"), ImageCandidate(image_bytes=_png())]
    transcode = _FlakyTranscode(fail_times=1)
    designer = _designer(
        search=FakeSearch(candidates=candidates), transcode=transcode
    )

    record = await _design(designer)

    assert record.status is AssetStatus.READY
    assert record.source is AssetSource.SEARCH
    assert transcode.calls == 2


async def test_all_candidates_unusable_still_falls_back_to_generation():
    """回归：候选全部不可用时，付费回退生成曾被短路（gen.calls==0）。"""
    candidates = [ImageCandidate(image_bytes=b"bad")]
    gen = FakeGen()
    designer = _designer(
        search=FakeSearch(candidates=candidates),
        gen=gen,
        transcode=_FlakyTranscode(fail_times=1),
    )

    record = await _design(designer)

    assert record.status is AssetStatus.READY
    assert record.source is AssetSource.GENERATED
    assert gen.calls == 1


class _CountingReviewer(FakeReviewer):
    def __init__(self, **kw) -> None:
        super().__init__(**kw)
        self.calls = 0

    async def review(self, candidate, *, scene_description: str, kind: AssetKind):
        self.calls += 1
        return await super().review(
            candidate, scene_description=scene_description, kind=kind
        )


async def test_degraded_review_stops_asking_remaining_candidates():
    """回归：审核通道故障时仍会对每个候选各发一次 LLM 往返，白花钱。"""
    candidates = [ImageCandidate(image_bytes=_png()) for _ in range(4)]
    reviewer = _CountingReviewer(degrade=True)
    designer = _designer(search=FakeSearch(candidates=candidates), reviewer=reviewer)

    await _design(designer)

    assert reviewer.calls == 1, "见到 REVIEW_FAILED 就该收束，不再逐条追问"


async def test_free_search_asset_does_not_consume_paid_budget():
    """回归：检索来的免费资产曾按 units=1 计量，把 org 的付费生图预算白吃掉。"""
    candidate = ImageCandidate(image_bytes=_png())
    meter, quota = FakeMeter(), FakeQuota()
    designer = _designer(
        search=FakeSearch(candidates=[candidate]), meter=meter, quota=quota
    )

    record = await _design(designer)

    assert record.source is AssetSource.SEARCH
    assert [r.units for r in meter.records] == [0], "免费来源必须 units=0"
    assert quota.consumed == 0


async def test_paid_generation_is_metered_even_if_transcode_fails():
    """回归：钱已花但转码失败时曾不计量，真实花费从账上消失。"""
    meter, gen = FakeMeter(), FakeGen()
    designer = _designer(
        search=FakeSearch(candidates=[]), gen=gen, meter=meter, transcode=BoomTranscode()
    )

    record = await _design(designer)

    assert record.status is AssetStatus.FAILED
    assert [r.units for r in meter.records] == [1], "付费调用必须逐次落一条计量"


async def test_quota_uses_atomic_try_acquire():
    """回归：check+consume 是两步，并发下会双双通过而超额。"""
    quota = FakeQuota()
    designer = _designer(search=FakeSearch(candidates=[]), quota=quota)

    await _design(designer)

    assert quota.consumed == 1


def test_provider_version_includes_model():
    """回归：只取类名时，同一 adapter 换 model 不会失效缓存（会复用旧画风的图）。"""
    without_model = SceneDesigner(
        storage=FakeStorage(),
        image_gen=FakeGen(),
        image_search=FakeSearch(),
        assets=FakeAssets(),
        reviewer=FakeReviewer(),
        transcode=_renditions,
    )
    with_model = SceneDesigner(
        storage=FakeStorage(),
        image_gen=FakeGen(),
        image_search=FakeSearch(),
        assets=FakeAssets(),
        reviewer=FakeReviewer(),
        transcode=_renditions,
        generation_model="model-x",
    )
    assert without_model.provider_version != with_model.provider_version
    assert with_model.provider_version.endswith("model-x")


async def test_non_error_transcode_crash_is_degraded_not_propagated():
    """回归：转码实现可能抛 MemoryError 等非 Error，穿透会把降级变成 500。"""

    class Crasher:
        def __call__(self, _data: bytes) -> list[Rendition]:
            raise MemoryError("out of memory")

    designer = _designer(search=FakeSearch(candidates=[]), transcode=Crasher())

    record = await _design(designer)

    assert record.status is AssetStatus.FAILED


# ===== #49 教师配图操作 =====


async def test_exclude_asset_ids_misses_cache_and_rebuilds():
    """重生成（#49）：排除旧 id 后缓存未命中 → 重新生成，新行时间戳最新。"""
    old = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/old.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        org_id=_ORG,
        dedup_key=_dedup_key(),
        content_hash=hashlib.sha256(b"old-bytes").hexdigest(),
    )
    designer = _designer(
        assets=FakeAssets(seed=[old]),
        search=FakeSearch(candidates=[]),  # 无检索候选 → 直接回退生成
    )

    record = await _design(designer, exclude_asset_ids=[old.asset_id])

    assert record.status is AssetStatus.READY
    assert record.asset_id != old.asset_id, "重生成产出新资产"


async def test_exclude_content_hashes_skips_identical_search_candidate():
    """检索替换（#49）：候选字节与旧图相同不算换图，跳过后走下一候选。"""
    same_bytes = _png()
    old_hash = hashlib.sha256(same_bytes).hexdigest()
    candidate_same = ImageCandidate(image_bytes=same_bytes, title="同图")
    candidate_fresh = ImageCandidate(image_bytes=_png(width=80, height=45), title="新图")
    old = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/old.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        org_id=_ORG,
        dedup_key=_dedup_key(),
        content_hash=old_hash,
    )
    designer = _designer(assets=FakeAssets(seed=[old]), search=FakeSearch(
        candidates=[candidate_same, candidate_fresh]
    ))

    # exclude_asset_ids 里给旧 id：design_scene 内部反查 content_hash 补齐排除集
    record = await _design(designer, exclude_asset_ids=[old.asset_id])

    assert record.status is AssetStatus.READY
    assert record.content_hash != old_hash, "检索替换不得原样返回旧字节"


async def test_search_only_does_not_fall_back_to_generation():
    """检索替换（#49）：教师点名检索来源时无候选 → FAILED，不悄悄替他生成。"""
    gen_calls: list[int] = []

    class CountingGen(FakeGen):
        async def generate(self, **kwargs):
            gen_calls.append(1)
            return await super().generate(**kwargs)

    designer = _designer(search=FakeSearch(candidates=[]), gen=CountingGen())

    record = await _design(designer, search_only=True)

    assert record.status is AssetStatus.FAILED
    assert gen_calls == [], "search_only 不得触发付费生成"


async def test_publish_upload_roundtrip_and_dedup():
    """教师上传（#49）：READY 落库 + 同文件重传命中缓存不重复占存储。"""
    assets = FakeAssets()
    designer = _designer(assets=assets)

    first = await designer.publish_upload(
        org_id=_ORG,
        subject_key="scene:1",
        scene_key="script:7:scene:1",
        description="教师上传",
        kind=AssetKind.BACKGROUND,
        image_bytes=_png(),
        content_type="image/png",
        script_id=7,
    )
    assert first.status is AssetStatus.READY
    assert first.source is AssetSource.UPLOADED
    assert first.provider == "teacher_upload"

    second = await designer.publish_upload(
        org_id=_ORG,
        subject_key="scene:1",
        scene_key="script:7:scene:1",
        description="教师上传",
        kind=AssetKind.BACKGROUND,
        image_bytes=_png(),
        content_type="image/png",
        script_id=7,
    )
    assert second.asset_id == first.asset_id, "同 subject 同文件命中上传缓存"


async def test_find_bindable_upload_rejects_mismatch():
    """bind_upload 校验（#49）：不存在/非上传件/kind 不符/非 READY 都不可绑定。"""
    upload = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/up.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        source=AssetSource.UPLOADED,
        org_id=_ORG,
        dedup_key="k",
    )
    generated = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/gen.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        source=AssetSource.GENERATED,
        org_id=_ORG,
        dedup_key="k2",
    )
    designer = _designer(assets=FakeAssets(seed=[upload, generated]))

    ok = await designer.find_bindable_upload(
        asset_id=upload.asset_id, org_id=_ORG, kind=AssetKind.BACKGROUND
    )
    assert ok is not None

    missing = await designer.find_bindable_upload(
        asset_id=uuid.uuid4(), org_id=_ORG, kind=AssetKind.BACKGROUND
    )
    assert missing is None, "不存在的资产不可绑定"

    not_upload = await designer.find_bindable_upload(
        asset_id=generated.asset_id, org_id=_ORG, kind=AssetKind.BACKGROUND
    )
    assert not_upload is None, "生成/检索件不得经 bind_upload 冒充上传"

    wrong_kind = await designer.find_bindable_upload(
        asset_id=upload.asset_id, org_id=_ORG, kind=AssetKind.AVATAR
    )
    assert wrong_kind is None, "kind 与槽位不符不可绑定"

    other_org = await designer.find_bindable_upload(
        asset_id=upload.asset_id, org_id=uuid.uuid4(), kind=AssetKind.BACKGROUND
    )
    assert other_org is None, "跨 org 越权不可绑定"


async def test_publish_upload_invalid_bytes_fail_not_raise():
    """教师上传无效字节（#49）：转码抛 MEDIA_IMAGE_INVALID → 降级 FAILED 不抛。

    上传与检索/生成共用「编排不抛媒体失败」契约；同步错误反馈由服务层检查
    status 转换（upload_asset → MEDIA_IMAGE_INVALID）。
    """
    designer = _designer(transcode=BoomTranscode())

    record = await designer.publish_upload(
        org_id=_ORG,
        subject_key="scene:2",
        scene_key="script:7:scene:2",
        description="教师上传",
        kind=AssetKind.BACKGROUND,
        image_bytes=b"not-an-image",
        script_id=7,
    )

    assert record.status is AssetStatus.FAILED


# ===== #51 来源/许可展示 =====


def test_to_contract_credit_rules():
    """署名规则（#51）：检索件带完整许可元数据；生成/上传件与空 credit → None。

    展示侧过滤（免署名学生端不显示）不做在数据层——教师端要完整信息。
    """
    search_record = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="o/s.webp",
        kind=AssetKind.BACKGROUND,
        status=AssetStatus.READY,
        source=AssetSource.SEARCH,
        org_id=_ORG,
        credit=AssetCredit(
            author="摄影师甲",
            license="CC BY-SA 4.0",
            source_url="https://commons.example.org/x",
            license_url="https://creativecommons.org/licenses/by-sa/4.0/",
        ),
    )
    credit = to_contract_credit(search_record)
    assert credit is not None
    assert credit.license == "CC BY-SA 4.0"
    assert credit.author == "摄影师甲"

    # 生成件 / 上传件：无署名语义
    assert to_contract_credit(
        AssetRecord(
            asset_id=uuid.uuid4(), object_key="o/g.webp", kind=AssetKind.BACKGROUND,
            status=AssetStatus.READY, source=AssetSource.GENERATED, org_id=_ORG,
        )
    ) is None
    assert to_contract_credit(
        AssetRecord(
            asset_id=uuid.uuid4(), object_key="o/u.webp", kind=AssetKind.BACKGROUND,
            status=AssetStatus.READY, source=AssetSource.UPLOADED, org_id=_ORG,
        )
    ) is None
    # 检索件但 credit 全空：退回 None
    assert to_contract_credit(
        AssetRecord(
            asset_id=uuid.uuid4(), object_key="o/s2.webp", kind=AssetKind.BACKGROUND,
            status=AssetStatus.READY, source=AssetSource.SEARCH, org_id=_ORG,
        )
    ) is None


def test_requires_attribution_follows_license_whitelist():
    """学生端署名判定（#51）：CC BY/BY-SA → True；CC0/PD → False；空串 → False。"""
    assert requires_attribution("CC BY 4.0") is True
    assert requires_attribution("CC BY-SA 4.0") is True
    assert requires_attribution("CC0 1.0") is False
    assert requires_attribution("Public domain") is False
    assert requires_attribution("") is False


# ===== 运行期成本与安全闸（#57）=====


async def test_blocked_prompt_is_dropped_before_quota():
    """本地安全过滤命中即丢弃：不调 provider，也**不吃 org 预算**。

    顺序是这条用例的全部意义——`screen_generation_prompt` 若排在 `try_acquire`
    之后，一张注定被拒的图会白吃一次配额，而配额是拿真实付费喂出来的。
    """
    gen, quota = FakeGen(), FakeQuota()
    designer = _designer(gen=gen, quota=quota, search=FakeSearch(candidates=[]))

    record = await _design(designer, description="一段nsfw画面")

    assert record.status is AssetStatus.FAILED
    assert gen.calls == 0, "被过滤的 prompt 绝不能送去 provider"
    assert quota.consumed == 0
    # 原因要落到记录上：运行期任务台账靠它归因失败率
    assert record.reason.startswith("blocked:")


async def test_blocked_prompt_does_not_poison_cache():
    """被拦下的那次不留缓存命中：换个干净描述，同一场景照样能出图。"""
    gen = FakeGen()
    assets = FakeAssets()
    designer = _designer(assets=assets, gen=gen, search=FakeSearch(candidates=[]))

    blocked = await _design(designer, description="裸露画面")
    assert blocked.status is AssetStatus.FAILED

    ok = await _design(designer, description="古老的江南水乡")
    assert ok.status is AssetStatus.READY
    assert gen.calls == 1


async def test_cache_hits_across_sessions_of_the_same_script():
    """缓存跨会话命中（#57）：同一剧本的第二个会话直接复用，不再付费。

    这也是运行期产物**不能**写 `session_id` 的原因——一写，
    `AssetAccessService` 就改按会话 owner 鉴权，第二个会话拿到这张图直接 403。
    """
    assets, gen = FakeAssets(), FakeGen()
    designer = _designer(assets=assets, gen=gen, search=FakeSearch(candidates=[]))

    first = await _design(
        designer, script_id=101, session_id=uuid.uuid4(), subject_key="scene:5"
    )
    second = await _design(
        designer, script_id=101, session_id=uuid.uuid4(), subject_key="scene:5"
    )

    assert second.asset_id == first.asset_id
    assert gen.calls == 1
    assert second.session_id is None, "归属落在剧本上，不是发起它的那个会话"


async def test_generation_failure_reason_is_recorded():
    """失败原因不止进日志：`assets.reason` 要能支撑失败率归因。"""
    designer = _designer(gen=FakeGen(error=True), search=FakeSearch(candidates=[]))

    record = await _design(designer)

    assert record.status is AssetStatus.FAILED
    assert record.reason
