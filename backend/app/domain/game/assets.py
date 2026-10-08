"""事件为权威的场景资产派生（ADR-0005 §9，issue #55）。

- 场景资产由 `EventStore.active_events()` / `branch_path()` 重放派生，复用既有分支
  血缘语义（回溯后继承前缀保留、被放弃分支的事件排除）——**不新增第二套继承逻辑**。
- `asset_ready` 事件载荷 `{scene_key, asset_id, kind?, status?}`；同一 `scene_key`
  后写覆盖先写（支持重生成/检索替换）。`kind` 缺省 `background`、`status` 缺省 `ready`
  （取自 `domain/game/media.py` 的 `AssetKind`/`AssetStatus`，不另立副本）。
- `RuntimeAssets` 只是可从事件重建的**非权威索引/缓存**；唯一权威始终是事件流。
  生产侧一律经 `RuntimeAssets.rebuild(store)` 重建——它内部走 `active_events()`，
  把「唯一权威」焊在接口上；不要自行把 `store.events`（含被放弃分支）或重放尾段
  喂给 `derive_scene_assets`，那会得到静默错误的映射。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from app.contracts.script import AssetRef
from app.domain.game.event import EVENT_ASSET_READY, EventStore, GameEvent
from app.domain.game.media import AssetKind, AssetStatus

logger = logging.getLogger(__name__)

_DEFAULT_KIND = AssetKind.BACKGROUND.value
_DEFAULT_STATUS = AssetStatus.READY.value

_EventLike = GameEvent | dict[str, Any]


def _event_type_and_payload(ev: _EventLike) -> tuple[str | None, dict[str, Any] | None]:
    """兼容 `GameEvent` 对象与 `GameEvent.to_dict()` 形状。"""
    if isinstance(ev, dict):
        return ev.get("event_type"), ev.get("payload")
    return getattr(ev, "event_type", None), getattr(ev, "payload", None)


def _ref_from_payload(payload: dict[str, Any]) -> AssetRef | None:
    asset_id = payload.get("asset_id")
    if not asset_id:
        return None
    try:
        return AssetRef(
            asset_id=asset_id,
            kind=str(payload.get("kind") or _DEFAULT_KIND),
            status=str(payload.get("status") or _DEFAULT_STATUS),
        )
    except ValidationError as exc:
        # 坏载荷（asset_id 非 UUID / kind·status 不在 Literal 内）跳过，不因单条坏事件
        # 中断整段重放；但必须记 warning——静默丢弃会让该 scene_key 回落到旧资产，
        # 前端一直显示过期背景且无从排查。
        logger.warning(
            "scene_asset_event_dropped",
            extra={"scene_key": payload.get("scene_key"), "reason": str(exc)},
        )
        return None


def derive_scene_assets(events: Iterable[_EventLike]) -> dict[str, AssetRef]:
    """重放事件，返回 `scene_key -> AssetRef` 的权威映射（后写覆盖先写）。

    传入序列**必须是活动分支的完整有序历史**（`EventStore.active_events()`），
    这样回溯/分支继承由既有 `branch_path` 语义自动承担。传 `store.events`
    （含被放弃分支）或快照后的重放尾段都会静默算错——生产侧请走
    `RuntimeAssets.rebuild(store)`。
    """
    out: dict[str, AssetRef] = {}
    for ev in events:
        event_type, payload = _event_type_and_payload(ev)
        if event_type != EVENT_ASSET_READY or not isinstance(payload, dict):
            continue
        scene_key = payload.get("scene_key")
        if not scene_key:
            continue
        ref = _ref_from_payload(payload)
        if ref is not None:
            out[str(scene_key)] = ref
    return out


@dataclass
class RuntimeAssets:
    """可从事件重建的非权威索引（唯一权威 = 事件流）。"""

    by_scene: dict[str, AssetRef] = field(default_factory=dict)

    @classmethod
    def rebuild(cls, store: EventStore) -> RuntimeAssets:
        """从 store 的**活动分支**事件重建索引（生产侧唯一权威入口，不落库）。"""
        return cls(by_scene=derive_scene_assets(store.active_events()))

    def current(self, scene_key: str | None) -> AssetRef | None:
        """取某场景当前资产；无则 None。"""
        if not scene_key:
            return None
        return self.by_scene.get(scene_key)


__all__ = ["RuntimeAssets", "derive_scene_assets"]
