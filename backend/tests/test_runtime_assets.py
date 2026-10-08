"""事件为权威的场景资产派生测试（issue #55 / ADR-0005 §9）。

验证：事件重放派生 scene_key→AssetRef、后写覆盖、回溯继承复用 branch_path、
重放一致（重建=增量）、坏事件跳过、dict/对象两种事件形状。
"""

from __future__ import annotations

import uuid

from app.domain.game.assets import RuntimeAssets, derive_scene_assets
from app.domain.game.event import EVENT_ASSET_READY, EventStore


def _aid(n: int) -> str:
    return str(uuid.UUID(int=n))


def _ready(
    store: EventStore,
    scene_key: str,
    asset_id: str,
    *,
    kind: str = "background",
    status: str = "ready",
):
    return store.append(
        EVENT_ASSET_READY,
        {
            "scene_key": scene_key,
            "asset_id": asset_id,
            "kind": kind,
            "status": status,
        },
    )


def test_derive_maps_scene_key_to_asset_ref():
    store = EventStore()
    _ready(store, "scene:1", _aid(1))
    _ready(store, "scene:2", _aid(2), kind="avatar", status="pending")

    assets = derive_scene_assets(store.active_events())

    assert set(assets) == {"scene:1", "scene:2"}
    assert assets["scene:1"].asset_id == uuid.UUID(_aid(1))
    assert assets["scene:1"].kind == "background"
    assert assets["scene:1"].status == "ready"
    assert assets["scene:2"].kind == "avatar"
    assert assets["scene:2"].status == "pending"


def test_later_event_wins_for_same_scene():
    store = EventStore()
    _ready(store, "scene:1", _aid(1))
    _ready(store, "scene:1", _aid(2))

    assets = derive_scene_assets(store.active_events())

    assert assets["scene:1"].asset_id == uuid.UUID(_aid(2))


def test_rollback_inherits_prefix_and_drops_superseded():
    store = EventStore()
    first = _ready(store, "scene:1", _aid(1))
    _ready(store, "scene:2", _aid(2))

    # 回溯到 first：新活动分支继承 first 之前的全部事件，scene:2 被放弃
    store.rollback_to(first.event_id)
    _ready(store, "scene:3", _aid(3))

    assets = derive_scene_assets(store.active_events())

    assert assets["scene:1"].asset_id == uuid.UUID(_aid(1))
    assert "scene:2" not in assets
    assert assets["scene:3"].asset_id == uuid.UUID(_aid(3))


def test_rebuild_is_consistent_and_reads_from_events():
    store = EventStore()
    _ready(store, "scene:1", _aid(1))
    _ready(store, "scene:2", _aid(2))

    index = RuntimeAssets.rebuild(store)

    assert index.current("scene:1").asset_id == uuid.UUID(_aid(1))
    assert index.current(None) is None
    assert index.current("scene:missing") is None
    # 重放一致：再次重建同一事件流得到相同索引（非权威、可重建）
    assert RuntimeAssets.rebuild(store).by_scene == index.by_scene


def test_malformed_events_are_skipped():
    store = EventStore()
    store.append(EVENT_ASSET_READY, {"asset_id": _aid(1)})  # 缺 scene_key
    store.append(EVENT_ASSET_READY, {"scene_key": "scene:1"})  # 缺 asset_id
    store.append(
        EVENT_ASSET_READY, {"scene_key": "scene:1", "asset_id": "not-a-uuid"}
    )  # 非法资产 id

    assert derive_scene_assets(store.active_events()) == {}


def test_accepts_dict_event_shape():
    events = [
        {
            "event_type": EVENT_ASSET_READY,
            "payload": {"scene_key": "scene:9", "asset_id": _aid(9)},
        }
    ]
    assert derive_scene_assets(events)["scene:9"].asset_id == uuid.UUID(_aid(9))


def test_rebuild_from_store_excludes_abandoned_branch():
    """`rebuild(store)` 走 active_events()：被回溯放弃的分支资产不得进入索引。

    这条断言把「唯一权威 = 活动分支」焊在接口上——若有人改成读 `store.events`
    （含全部历史分支），本用例立即变红。
    """
    store = EventStore()
    first = _ready(store, "scene:1", _aid(1))
    _ready(store, "scene:2", _aid(2))  # 将被放弃
    store.rollback_to(first.event_id)
    _ready(store, "scene:2", _aid(3))  # 新分支重写同一 scene_key

    index = RuntimeAssets.rebuild(store)

    assert index.current("scene:2") is not None
    assert index.current("scene:2").asset_id == uuid.UUID(_aid(3))

    # 对照：store.events 含被放弃分支，直喂 derive_scene_assets 会算错（顺序上旧值在后亦可覆盖）
    assert len(store.events) > len(store.active_events())


def test_bad_payload_logs_warning():
    """坏载荷跳过但必须留痕：静默丢弃会让该 scene_key 回落旧资产、前端一直显示过期背景。

    caplog 在全量套件下不可靠（其他测试改动 logging 配置），按 test_rag 的探针做法断言调用。
    """
    import app.domain.game.assets as assets_mod

    captured: list[tuple[str, dict]] = []

    class _Probe:
        def warning(self, msg, *args, **kwargs):
            captured.append((msg, kwargs.get("extra", {})))

    store = EventStore()
    store.append(EVENT_ASSET_READY, {"scene_key": "scene:1", "asset_id": "not-a-uuid"})

    orig = assets_mod.logger
    assets_mod.logger = _Probe()
    try:
        assert derive_scene_assets(store.active_events()) == {}
    finally:
        assets_mod.logger = orig

    assert [msg for msg, _ in captured] == ["scene_asset_event_dropped"]
    assert captured[0][1]["scene_key"] == "scene:1"
