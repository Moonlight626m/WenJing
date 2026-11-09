"""Stage3 确定性探索骨架（design play-through-redesign §B3，里程碑 M5/M6）。

职责边界：只做**确定性**的事——地点注册表、在场过滤、换景与每轮结算；
运行期世界（动态场景/新角色/拉人/世界事实，M6 §B5/B6）也在这里由事件派生。
NPC 的提议/反应仍是 LLM（`CharacterAgent`）；导演（选项）与世界构建（干涉解析）
是工作人员 agent（`domain/agents/director.py`、`world_builder.py`），只经事件与
本模块的世界模型交互。旧剧本（`exploration=None`）完全不走这里，保持原有
3 轮行为。

在场是唯一事实源：地点的 `participants` 成员集合（+ 运行期拉入/新增）= 该地点
在场角色（`ExplorationDirector.participants_at` 是唯一拼法）；运行时按
`scene_switch` / `exploration_settle` / `scene_created` 等事件重建进度与世界。
地点稳定键 `loc:{location_key}` 与事件、配图槽位同一拼法。
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from app.contracts.script import ExplorationLocation, ExplorationMap
from app.domain.game import event as evt

logger = logging.getLogger("wenjing.core.exploration")

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


def build_location_registry(map: ExplorationMap | None) -> LocationRegistry | None:
    """`exploration=None` 或起点缺失 → None（旧剧本/非法地图走原 3 轮路径）。"""
    if map is None:
        return None
    locations = {raw.location_key: _to_location(raw) for raw in map.locations}
    if map.start_location_key not in locations:
        logger.warning(
            "exploration_start_location_missing",
            extra={"start": map.start_location_key},
        )
        return None
    return LocationRegistry(locations, map.start_location_key)


def _location_key_of(payload: dict[str, Any]) -> str | None:
    """`scene_created` 载荷 → 地点键（显式 location_key 优先，其次 scene_key 去前缀）。"""
    key = payload.get("location_key")
    if isinstance(key, str) and key:
        return key
    scene_key = payload.get("scene_key")
    if isinstance(scene_key, str) and scene_key:
        return scene_key.removeprefix(SCENE_KEY_PREFIX)
    return None


def derive_exploration(
    events: Iterable[Any], registry: LocationRegistry
) -> ExplorationProgress:
    """从活动分支事件折叠探索进度（接受 `GameEvent` 或 `to_dict()`）。

    运行期新增的地点（`scene_created`，M6）在事件流里先于任何 `scene_switch`
    出现，故与地点表一起构成「已存在地点」集合——换进动态场景的进度不会丢。
    """
    current = registry.start_key
    visited: list[str] = [current]
    dynamic: set[str] = set()
    for ev in events:
        if isinstance(ev, dict):
            etype = ev.get("event_type")
            payload = ev.get("payload") or {}
        else:
            etype = getattr(ev, "event_type", None)
            payload = getattr(ev, "payload", None) or {}
        if etype == evt.EVENT_SCENE_CREATED:
            key = _location_key_of(payload)
            if key is not None:
                dynamic.add(key)
            continue
        key: str | None = None
        if etype == evt.EVENT_SCENE_SWITCH:
            key = payload.get("to")
        elif etype == evt.EVENT_EXPLORATION_SETTLE:
            key = payload.get("location_key")
        if not isinstance(key, str) or (
            key not in dynamic and registry.get(key) is None
        ):
            continue
        current = key
        if key not in visited:
            visited.append(key)
    return ExplorationProgress(current_location_key=current, visited=tuple(visited))


@dataclass(frozen=True)
class WorldFact:
    """世界事实：`visibility=private` 只进 `audience` 的角色视图（§B6）。"""

    fact_id: str
    kind: str
    text: str
    visibility: str = "public"
    audience: tuple[str, ...] = ()
    location_key: str | None = None

    def visible_to(self, viewer: str | None) -> bool:
        if self.visibility != "private":
            return True
        return viewer is not None and viewer in self.audience


@dataclass(frozen=True)
class WorldState:
    """运行期新增的世界（M6）：动态场景、新角色、拉人入场、世界事实。

    全部由事件派生（`scene_created` / `character_created` / `pull_in_character` /
    `world_fact`），回溯到创建之前 = 它们从未存在。
    """

    dynamic_scenes: dict[str, Location] = field(default_factory=dict)
    characters: dict[str, dict[str, Any]] = field(default_factory=dict)
    # scene_key -> 额外在场角色（`character_created` 的所在地、`pull_in_character`）
    memberships: dict[str, tuple[str, ...]] = field(default_factory=dict)
    facts: tuple[WorldFact, ...] = ()

    def facts_for(self, viewer: str | None) -> tuple[WorldFact, ...]:
        return tuple(f for f in self.facts if f.visible_to(viewer))

    def members_at(self, scene_key: str | None) -> tuple[str, ...]:
        if scene_key is None:
            return ()
        return self.memberships.get(scene_key, ())


def _event_type_payload(ev: Any) -> tuple[str | None, dict[str, Any]]:
    if isinstance(ev, dict):
        return ev.get("event_type"), ev.get("payload") or {}
    return getattr(ev, "event_type", None), getattr(ev, "payload", None) or {}


def derive_world(events: Iterable[Any]) -> WorldState:
    """从活动分支事件折叠运行期世界（动态场景/角色/在场/事实）。"""
    scenes: dict[str, Location] = {}
    characters: dict[str, dict[str, Any]] = {}
    memberships: dict[str, set[str]] = {}
    facts: list[WorldFact] = []

    for ev in events:
        etype, payload = _event_type_payload(ev)
        if etype == evt.EVENT_SCENE_CREATED:
            scene_key = payload.get("scene_key")
            title = payload.get("title")
            if not isinstance(scene_key, str) or not scene_key or not title:
                continue
            key = _location_key_of(payload) or scene_key
            participants = tuple(
                str(n) for n in payload.get("participants", []) if n
            )
            scenes[scene_key] = Location(
                location_key=str(key),
                scene_key=scene_key,
                title=str(title),
                participants=participants,
                visual_summary=str(payload.get("visual_summary", "")),
            )
            memberships.setdefault(scene_key, set()).update(participants)
        elif etype == evt.EVENT_CHARACTER_CREATED:
            name = payload.get("name")
            if not isinstance(name, str) or not name:
                continue
            characters[name] = payload
            location_key = payload.get("location_key")
            if isinstance(location_key, str) and location_key:
                scene_key = location_scene_key(location_key)
                memberships.setdefault(scene_key, set()).add(name)
        elif etype == evt.EVENT_PULL_IN_CHARACTER:
            name = payload.get("name")
            to_scene = payload.get("to_scene")
            if isinstance(name, str) and name and isinstance(to_scene, str):
                memberships.setdefault(to_scene, set()).add(name)
        elif etype == evt.EVENT_WORLD_FACT:
            fact_id = payload.get("fact_id")
            text = payload.get("text")
            if not isinstance(fact_id, str) or not isinstance(text, str):
                continue
            facts.append(
                WorldFact(
                    fact_id=fact_id,
                    kind=str(payload.get("kind", "")),
                    text=text,
                    visibility=str(payload.get("visibility", "public")),
                    audience=tuple(
                        str(n) for n in payload.get("audience", []) if n
                    ),
                    location_key=payload.get("location_key"),
                )
            )

    return WorldState(
        dynamic_scenes=scenes,
        characters=characters,
        memberships={k: tuple(v) for k, v in memberships.items()},
        facts=tuple(facts),
    )


class ExplorationDirector:
    """确定性探索编排：进度、在场、结算、换景列表。零 LLM。"""

    def __init__(self, registry: LocationRegistry) -> None:
        self.registry = registry

    def start_progress(self) -> ExplorationProgress:
        return ExplorationProgress(current_location_key=self.registry.start_key,
                                   visited=(self.registry.start_key,))

    def progress(self, events: Any) -> ExplorationProgress:
        return derive_exploration(events, self.registry)

    def location(
        self, location_key: str, world: WorldState | None = None
    ) -> Location | None:
        static = self.registry.get(location_key)
        if static is not None:
            return static
        if world is not None:
            return world.dynamic_scenes.get(location_scene_key(location_key))
        return None

    def resolve_scene(
        self, scene_key: str, world: WorldState | None = None
    ) -> Location | None:
        static = self.registry.by_scene_key(scene_key)
        if static is not None:
            return static
        if world is not None:
            return world.dynamic_scenes.get(scene_key)
        return None

    def participants_at(
        self, location: Location, world: WorldState | None = None
    ) -> tuple[str, ...]:
        """地点的在场名单：静态 `participants` + 运行期拉入/新增（保序去重）。

        「在场」口径的唯一拼法——`present_names`、换景 payload、世界视图的
        知识边界都从这里取，避免三处各写一遍后漂移。
        """
        names = list(location.participants)
        if world is not None:
            names.extend(
                n for n in world.members_at(location.scene_key) if n not in names
            )
        return tuple(names)

    def present_names(
        self,
        progress: ExplorationProgress,
        active_names: tuple[str, ...],
        world: WorldState | None = None,
    ) -> tuple[str, ...]:
        """在场 = 地点 participants（+ 运行期拉入/新增）∩ 已创建角色。"""
        location = self.location(progress.current_location_key, world)
        if location is None:
            return ()
        candidates = set(self.participants_at(location, world))
        return tuple(name for name in active_names if name in candidates)

    def settle(
        self,
        progress: ExplorationProgress,
        action_text: str,
        present: tuple[str, ...],
        world: WorldState | None = None,
    ) -> Settlement | None:
        """把玩家这一轮的动作结算成地点化的摘要/处境（确定性、可重放）。"""
        location = self.location(progress.current_location_key, world)
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

    def scene_options(
        self, progress: ExplorationProgress, world: WorldState | None = None
    ) -> list[dict[str, Any]]:
        """交互点换景列表（契约投影前的普通 dict，当前地点标 is_current）。

        M5 的静态地图是平铺地点表；M6 的动态场景（`scene_created`）追加在后面，
        连通/解锁过滤仍留给后续。
        """
        locations = list(self.registry.ordered())
        if world is not None:
            known = {loc.scene_key for loc in locations}
            locations.extend(
                loc
                for key, loc in world.dynamic_scenes.items()
                if key not in known
            )
        return [
            {
                "scene_key": location.scene_key,
                "title": location.title,
                # 与 present_names / 换景 payload 同一口径：静态名单 + 运行期拉入/新增
                "participants": list(self.participants_at(location, world)),
                "is_current": location.location_key == progress.current_location_key,
            }
            for location in locations
        ]


__all__ = [
    "ExplorationDirector",
    "ExplorationProgress",
    "Location",
    "LocationRegistry",
    "Settlement",
    "WorldFact",
    "WorldState",
    "build_location_registry",
    "derive_exploration",
    "derive_world",
    "location_scene_key",
]
