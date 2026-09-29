"""媒体端口骨架形状测试（issue #39 M0）。

覆盖：七个端口的形状（方法与参数名）+ 空实现满足协议 + 去重键与 tee 缓冲语义。
"""

from __future__ import annotations

import inspect
import uuid

from app.domain.game.media import (
    AssetJobPort,
    AssetKind,
    AssetRecord,
    AssetRepositoryPort,
    AssetStatus,
    ImageGenPort,
    ImageSearchPort,
    MediaKind,
    MediaMeterPort,
    MediaQuotaPort,
    MediaUsage,
    ObjectStoragePort,
    SceneDesigner,
    build_dedup_key,
)
from app.domain.game.streaming import StreamTee, TextDelta
from app.infrastructure.media import (
    NullAssetRepository,
    NullImageGen,
    NullImageSearch,
    NullMediaMeter,
    NullMediaQuota,
    NullObjectStorage,
)

PORTS = (
    ObjectStoragePort,
    ImageGenPort,
    ImageSearchPort,
    AssetJobPort,
    AssetRepositoryPort,
    MediaMeterPort,
    MediaQuotaPort,
)


def _methods(protocol: type) -> dict[str, inspect.Signature]:
    return {
        name: inspect.signature(value)
        for name, value in vars(protocol).items()
        if not name.startswith("_") and callable(value)
    }


def test_ports_are_runtime_checkable_protocols():
    for port in PORTS:
        assert getattr(port, "_is_protocol", False), port
        assert getattr(port, "_is_runtime_protocol", False), port


def test_port_method_shapes():
    assert set(_methods(ObjectStoragePort)) == {"put", "presign"}
    assert set(_methods(ImageGenPort)) == {"generate"}
    assert set(_methods(ImageSearchPort)) == {"search"}
    assert set(_methods(AssetRepositoryPort)) == {
        "save",
        "get_by_id",
        "find_by_dedup_key",
        "fail_stale_pending",
    }
    assert set(_methods(AssetJobPort)) == {"open", "finish", "pending", "expire"}
    assert set(_methods(MediaMeterPort)) == {"record"}
    assert set(_methods(MediaQuotaPort)) == {"try_acquire", "check", "consume"}


def test_port_keyword_only_params():
    """端口方法用 keyword-only 参数，避免位置参数漂移。"""

    assert set(_methods(ObjectStoragePort)["put"].parameters) == {
        "self",
        "object_key",
        "data",
        "content_type",
    }
    put_params = _methods(ObjectStoragePort)["put"].parameters
    assert put_params["data"].kind is inspect.Parameter.KEYWORD_ONLY
    assert set(_methods(AssetRepositoryPort)["find_by_dedup_key"].parameters) == {
        "self",
        "org_id",
        "dedup_key",
        "status",
    }
    assert set(_methods(AssetJobPort)["finish"].parameters) == {
        "self",
        "job_id",
        "status",
        "asset_id",
        "reason",
    }
    assert set(_methods(AssetJobPort)["pending"].parameters) == {"self", "since"}
    for method in ("try_acquire", "check", "consume"):
        assert set(_methods(MediaQuotaPort)[method].parameters) == {
            "self",
            "org_id",
            "kind",
            "units",
        }


def test_null_impls_satisfy_ports():
    assert isinstance(NullObjectStorage(), ObjectStoragePort)
    assert isinstance(NullImageGen(), ImageGenPort)
    assert isinstance(NullImageSearch(), ImageSearchPort)
    assert isinstance(NullAssetRepository(), AssetRepositoryPort)
    assert isinstance(NullMediaMeter(), MediaMeterPort)
    assert isinstance(NullMediaQuota(), MediaQuotaPort)


async def test_null_impls_are_safe_noops():
    assert await NullObjectStorage().presign(object_key="a/b.png") == ""
    assert (await NullImageGen().generate(prompt="x", kind=AssetKind.BACKGROUND)).image_bytes == b""
    assert await NullImageSearch().search(query="x") == []
    assert await NullAssetRepository().get_by_id(uuid.uuid4()) is None
    assert await NullMediaMeter().record(
        MediaUsage(kind=MediaKind.IMAGE, provider="null")
    ) is None
    assert await NullMediaQuota().check(org_id=uuid.uuid4(), kind=MediaKind.IMAGE) is True


def test_asset_record_defaults_are_pending():
    record = AssetRecord(
        asset_id=uuid.uuid4(),
        object_key="org/a.png",
        kind=AssetKind.BACKGROUND,
    )
    assert record.status is AssetStatus.PENDING
    assert record.version == 1
    assert record.credit.author == ""


def test_build_dedup_key_is_org_scoped_and_normalized():
    org = uuid.uuid4()
    other = uuid.uuid4()
    key = build_dedup_key(
        org_id=org,
        subject_key="scene:1",
        description_summary="  古老  的村庄 ",
        style="水墨",
        provider_version="v1",
    )
    assert key == build_dedup_key(
        org_id=org,
        subject_key="scene:1",
        description_summary="古老 的村庄",
        style="水墨",
        provider_version="v1",
    )
    assert key != build_dedup_key(
        org_id=other,
        subject_key="scene:1",
        description_summary="古老 的村庄",
        style="水墨",
        provider_version="v1",
    )


class _NoopReviewer:
    """骨架形状测试不该走到审核：走到就报错。"""

    async def review(self, candidate, *, scene_description, kind):
        raise AssertionError("reviewer should not be called in a shape test")


def _noop_transcode(_data: bytes) -> list:
    return []


def test_scene_designer_holds_ports():
    designer = SceneDesigner(
        storage=NullObjectStorage(),
        image_gen=NullImageGen(),
        image_search=NullImageSearch(),
        assets=NullAssetRepository(),
        reviewer=_NoopReviewer(),
        transcode=_noop_transcode,
        meter=NullMediaMeter(),
        quota=NullMediaQuota(),
    )
    assert isinstance(designer.storage, ObjectStoragePort)
    # 去重键的 provider_version 默认跟随生图实现，换 provider 即失效缓存
    assert designer.provider_version == "NullImageGen"


def test_stream_tee_drops_oldest_over_capacity():
    tee = StreamTee(max_buffer=2)
    for i in range(4):
        tee.push(TextDelta(stream_id="s", speaker="甲", text=str(i)))
    assert [d.text for d in tee.drain()] == ["2", "3"]
    assert tee.drain() == []
