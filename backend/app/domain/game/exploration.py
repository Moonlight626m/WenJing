"""Stage3 确定性探索骨架（design play-through-redesign §B3，里程碑 M5）。

职责边界：只做**确定性**的事——地点注册表、在场过滤、换景与每轮结算。
NPC 的提议/反应仍是 LLM（`CharacterAgent`），导演与制作人（选项设计、干涉解析）
在 M6 才接。旧剧本（`exploration=None`）完全不走这里，保持原有 3 轮行为。

在场是唯一事实源：地点的 `participants` 成员集合 = 该地点在场角色；运行时按
`scene_switch` / `exploration_settle` 事件重建进度（回溯后自动回退）。
地点稳定键 `loc:{location_key}` 与事件、配图槽位同一拼法。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.contracts.script import ExplorationLocation, ExplorationMap
from app.domain.game import event as evt

SCENE_KEY_PREFIX = "loc:"


def location_scene_key(location_key: str) -> str:
    return f"{SCENE_KEY_PREFIX}{location_key}"


@dataclass(frozen=True)
class Location:
    location_key: str
    scene_key: str
    title: str
    participants: tuple[str, ...]
    visual_summary: str


@dataclass(frozen=True)
class ExplorationProgress:
    """当前地点 + 已访问地点（由事件折叠，不进 `_RState`）。"""

    current_location_key: str
    visited: tuple[str, ...] = ()


@dataclass(frozen=True)
class Settlement:
    """一轮的确定性结算结果（写 `exploration_settle` 事件）。"""

    location_key: str
    scene_key: str
    title: str
    summary: str
    conflict: str
    context: str
    present: tuple[str, ...]


def _to_location(raw: ExplorationLocation) -> Location:
    return Location(
        location_key=raw.location_key,
        scene_key=location_scene_key(raw.location_key),
        title=raw.title,
        participants=tuple(raw.participants),
        visual_summary=raw.visual_summary,
    )


class LocationRegistry:
    """地点表：顺序即前端换景列表顺序。"""

    def __init__(self, locations: dict[str, Location], start_key: str) -> None:
        self.locations = locations
        self.start_key = start_key

    def get(self, location_key: str) -> Location | None:
        return self.locations.get(location_key)

    def by_scene_key(self, scene_key: str) -> Location | None:
        if not scene_key.startswith(SCENE_KEY_PREFIX):
            return None
        return self.get(scene_key[len(SCENE_KEY_PREFIX) :])

    def ordered(self) -> tuple[Location, ...]:
        return tuple(self.locations.values())

    def start(self) -> Location | None:
        return self.get(self.start_key)

    def available(self, progress: ExplorationProgress) -> tuple[Location, ...]:
        """可前往的地点：M5 的地图是平铺地点表（无地点间连边），全部可达；
        当前地点也在列表里，由调用方标 `is_current`。地点间解锁是 M6。"""
        return self.ordered()


def build_location_registry(map: ExplorationMap | None) -> LocationRegistry | None:
    """`exploration=None` 或起点缺失 → None（旧剧本/非法地图走原 3 轮路径）。"""
    if map is None:
        return None
    locations = {raw.location_key: _to_location(raw) for raw in map.locations}
    if map.start_location_key not in locations:
        return None
    return LocationRegistry(locations, map.start_location_key)


def derive_exploration(
    events: Any, registry: LocationRegistry
) -> ExplorationProgress:
    """从活动分支事件折叠探索进度（`GameEvent` 或 `to_dict()` 均可）。"""
    current = registry.start_key
    visited: list[str] = [current]
    for ev in events:
        if isinstance(ev, dict):
            etype = ev.get("event_type") or ev.get("type")
            payload = ev.get("payload") or {}
        else:
            etype = getattr(ev, "event_type", None)
            payload = getattr(ev, "payload", None) or {}
        key: str | None = None
        if etype == evt.EVENT_SCENE_SWITCH:
            key = payload.get("to")
        elif etype == evt.EVENT_EXPLORATION_SETTLE:
            key = payload.get("location_key")
        if not isinstance(key, str) or registry.get(key) is None:
            continue
        current = key
        if key not in visited:
            visited.append(key)
    return ExplorationProgress(current_location_key=current, visited=tuple(visited))


class ExplorationDirector:
    """确定性探索编排：进度、在场、结算、换景列表。零 LLM。"""

    def __init__(self, registry: LocationRegistry) -> None:
        self.registry = registry

    def start_progress(self) -> ExplorationProgress:
        return ExplorationProgress(current_location_key=self.registry.start_key,
                                   visited=(self.registry.start_key,))

    def progress(self, events: Any) -> ExplorationProgress:
        return derive_exploration(events, self.registry)

    def present_names(
        self, progress: ExplorationProgress, active_names: tuple[str, ...]
    ) -> tuple[str, ...]:
        """在场 = 地点 participants ∩ 已创建角色；地点未登记 → 无人（不广播）。"""
        location = self.registry.get(progress.current_location_key)
        if location is None:
            return ()
        return tuple(name for name in location.participants if name in active_names)

    def settle(
        self,
        progress: ExplorationProgress,
        action_text: str,
        present: tuple[str, ...],
    ) -> Settlement | None:
        """把玩家这一轮的动作结算成地点化的摘要/处境（确定性、可重放）。"""
        location = self.registry.get(progress.current_location_key)
        if location is None:
            return None
        action = action_text.strip()
        summary = f"在「{location.title}」：{action}" if action else f"在「{location.title}」"
        context = location.visual_summary or f"当前地点：{location.title}"
        return Settlement(
            location_key=location.location_key,
            scene_key=location.scene_key,
            title=location.title,
            summary=summary,
            conflict=f"{location.title}：{action}" if action else location.title,
            context=context,
            present=present,
        )

    def scene_options(self, progress: ExplorationProgress) -> list[dict[str, Any]]:
        """交互点换景列表（契约投影前的普通 dict，当前地点标 is_current）。"""
        return [
            {
                "scene_key": location.scene_key,
                "title": location.title,
                "participants": list(location.participants),
                "is_current": location.location_key == progress.current_location_key,
            }
            for location in self.registry.available(progress)
        ]


__all__ = [
    "ExplorationDirector",
    "ExplorationProgress",
    "Location",
    "LocationRegistry",
    "Settlement",
    "build_location_registry",
    "derive_exploration",
    "location_scene_key",
]
