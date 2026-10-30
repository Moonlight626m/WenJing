"""图片审核 agent 测试（issue #45 / ADR-0005 §6）。

- 许可白名单/署名判定为纯函数测试。
- 审核路由与降级：许可不兼容不调 LLM；相关/画质走结构化输出；LLM 失败降级拒绝。
- token 计量：经 `UsageRecordingLLM` 写入 `llm_usage`，purpose=image_review（PG 集成）。
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.infrastructure.models  # noqa: F401
from app.contracts.enums import UsagePurpose
from app.domain.game.image_review import (
    ImageReviewAgent,
    LicenseStatus,
    ReviewReason,
    evaluate_license,
)
from app.domain.game.media import AssetCredit, AssetKind, ImageCandidate
from app.infrastructure.usage import UsageContext, UsageRecorder, UsageRecordingLLM

_DB_URL = os.environ.get(
    "WENJING_DATABASE_URL", "postgresql+asyncpg://wenjing:wenjing@localhost:5432/wenjing"
)


def _candidate(
    *,
    license: str = "CC0 1.0",
    title: str = "Ancient castle",
    description: str = "a castle on a hill",
    width: int = 1600,
    height: int = 900,
) -> ImageCandidate:
    return ImageCandidate(
        image_bytes=b"fake",
        content_type="image/jpeg",
        source_url="https://openverse.example/x",
        width=width,
        height=height,
        title=title,
        description=description,
        credit=AssetCredit(
            author="Alice",
            license=license,
            source_url="https://openverse.example/x",
            license_url="https://creativecommons.org/",
        ),
    )


class _ScriptedLLM:
    """确定性 LLM：返回预设文本或抛预设异常，并记录调用用途。"""

    provider = "test-provider"
    model = "test-model"

    def __init__(self, reply: str | Exception) -> None:
        self._reply = reply
        self.calls = 0
        self.purposes: list[UsagePurpose | None] = []

    async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        self.calls += 1
        self.purposes.append(purpose)
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


# ===== 许可白名单 / 署名判定（纯函数）=====


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("CC0 1.0", LicenseStatus.ATTRIBUTION_FREE),
        ("CC0", LicenseStatus.ATTRIBUTION_FREE),
        ("Creative Commons Zero", LicenseStatus.ATTRIBUTION_FREE),
        ("Public domain", LicenseStatus.ATTRIBUTION_FREE),
        ("PDM 1.0", LicenseStatus.ATTRIBUTION_FREE),
        ("CC BY 4.0", LicenseStatus.ATTRIBUTION_REQUIRED),
        ("CC BY-SA 4.0", LicenseStatus.ATTRIBUTION_REQUIRED),
        ("BY-SA 3.0", LicenseStatus.ATTRIBUTION_REQUIRED),
        ("Creative Commons Attribution 4.0", LicenseStatus.ATTRIBUTION_REQUIRED),
        ("CC BY-NC-SA 4.0", LicenseStatus.INCOMPATIBLE),
        ("CC BY-NC 4.0", LicenseStatus.INCOMPATIBLE),
        ("CC BY-ND 4.0", LicenseStatus.INCOMPATIBLE),
        ("All rights reserved", LicenseStatus.INCOMPATIBLE),
        ("", LicenseStatus.INCOMPATIBLE),
        ("GFDL", LicenseStatus.INCOMPATIBLE),
    ],
)
def test_evaluate_license(raw, expected):
    assert evaluate_license(raw) is expected


# ===== 审核路由与降级 =====


async def test_review_accepts_relevant_quality_candidate():
    llm = _ScriptedLLM('{"relevant": true, "quality_ok": true, "score": 0.9, "reason": "ok"}')
    agent = ImageReviewAgent(llm)

    result = await agent.review(
        _candidate(), scene_description="古堡远景", kind=AssetKind.BACKGROUND
    )

    assert result.accepted is True
    assert result.reason is ReviewReason.ACCEPTED
    assert result.degraded is False
    assert result.relevant and result.quality_ok
    assert result.score == 0.9
    assert result.license_status is LicenseStatus.ATTRIBUTION_FREE
    assert result.attribution_required is False
    assert llm.purposes == [UsagePurpose.IMAGE_REVIEW]


async def test_review_rejects_low_relevance():
    llm = _ScriptedLLM('{"relevant": false, "quality_ok": true, "reason": "无关"}')
    result = await ImageReviewAgent(llm).review(
        _candidate(), scene_description="古堡远景", kind=AssetKind.BACKGROUND
    )
    assert result.accepted is False
    assert result.reason is ReviewReason.IRRELEVANT
    assert result.relevant is False


async def test_review_rejects_low_quality():
    llm = _ScriptedLLM('{"relevant": true, "quality_ok": false, "reason": "分辨率过低"}')
    result = await ImageReviewAgent(llm).review(
        _candidate(width=64, height=64),
        scene_description="古堡远景",
        kind=AssetKind.BACKGROUND,
    )
    assert result.accepted is False
    assert result.reason is ReviewReason.LOW_QUALITY
    assert result.quality_ok is False


async def test_license_incompatible_rejected_without_llm():
    llm = _ScriptedLLM('{"relevant": true, "quality_ok": true}')
    result = await ImageReviewAgent(llm).review(
        _candidate(license="CC BY-NC-SA 4.0"),
        scene_description="古堡远景",
        kind=AssetKind.BACKGROUND,
    )
    assert result.accepted is False
    assert result.license_status is LicenseStatus.INCOMPATIBLE
    assert result.reason is ReviewReason.LICENSE_INCOMPATIBLE
    assert result.degraded is False
    assert llm.calls == 0


async def test_attribution_required_license_is_accepted_but_flagged():
    llm = _ScriptedLLM('{"relevant": true, "quality_ok": true}')
    result = await ImageReviewAgent(llm).review(
        _candidate(license="CC BY-SA 4.0"),
        scene_description="古堡远景",
        kind=AssetKind.BACKGROUND,
    )
    assert result.accepted is True
    assert result.reason is ReviewReason.ACCEPTED
    assert result.license_status is LicenseStatus.ATTRIBUTION_REQUIRED
    assert result.attribution_required is True


async def test_llm_failure_degrades_to_reject():
    llm = _ScriptedLLM(RuntimeError("provider down"))
    result = await ImageReviewAgent(llm).review(
        _candidate(license="CC BY-SA 4.0"),
        scene_description="古堡远景",
        kind=AssetKind.BACKGROUND,
    )
    assert result.accepted is False
    assert result.reason is ReviewReason.REVIEW_FAILED
    assert result.degraded is True
    # 未采用时不应给出署名要求（否则与 accepted=False 自相矛盾）
    assert result.attribution_required is False
    assert llm.calls == 1


async def test_unparseable_output_degrades_to_reject():
    llm = _ScriptedLLM("完全不是 JSON")
    result = await ImageReviewAgent(llm).review(
        _candidate(), scene_description="古堡远景", kind=AssetKind.BACKGROUND
    )
    assert result.accepted is False
    assert result.reason is ReviewReason.REVIEW_FAILED
    assert result.degraded is True


# ===== token 计量（PG 集成）=====


@pytest.fixture(scope="module")
def anyio_backend():
    return "asyncio"


async def _db_available() -> bool:
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    try:
        async with engine.connect() as conn:
            await conn.execute(text("select 1"))
        return True
    except Exception:
        return False
    finally:
        await engine.dispose()


@pytest.fixture(scope="module")
async def factory():
    if not await _db_available():
        pytest.skip("PostgreSQL 未可用，跳过图片审核计量集成测试")
    engine = create_async_engine(_DB_URL, pool_timeout=5, connect_args={"timeout": 5})
    async with engine.begin() as conn:
        from conftest import reset_baseline_schema

        await reset_baseline_schema(conn)
    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        async with engine.begin() as conn:
            from conftest import drop_baseline_schema

            await drop_baseline_schema(conn)
        await engine.dispose()


async def test_review_records_image_review_usage(factory):
    from conftest import create_actor
    from sqlalchemy import select

    from app.infrastructure.models.llm_usage import LlmUsage

    actor = await create_actor(factory, name="图片审核计量学校")
    recorder = UsageRecorder(session_factory=factory)
    inner = _ScriptedLLM('{"relevant": true, "quality_ok": true, "reason": "ok"}')
    llm = UsageRecordingLLM(
        inner,
        recorder=recorder,
        context=UsageContext(org_id=actor.org_id, user_id=actor.user_id, script_id=7),
    )
    agent = ImageReviewAgent(llm)

    await agent.review(_candidate(), scene_description="古堡远景", kind=AssetKind.BACKGROUND)

    async with factory() as s:
        rows = (
            await s.execute(select(LlmUsage).where(LlmUsage.org_id == actor.org_id))
        ).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.purpose == "image_review"
    assert row.script_id == 7
    assert row.total_tokens == row.prompt_tokens + row.completion_tokens
    assert row.total_tokens > 0
