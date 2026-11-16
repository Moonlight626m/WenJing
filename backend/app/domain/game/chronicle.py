"""编年史读模型：把 `world_chronicle` 事件按观众拼成限知叙事。

Chronicler 每轮只写**增量**一段；本模块只做拼接与可见性过滤，不调用 LLM、
不持久化第二份真相。`viewer=None` 是全知/工作人员视图；`viewer=name` 只返回
该角色在场（`present`）的增量。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from app.domain.game.event import EVENT_WORLD_CHRONICLE


@dataclass(frozen=True)
class ChronicleEntry:
    round: int
    text: str
    present: tuple[str, ...]
    location_key: str | None
    covers_event_id: int


def _type_payload(ev: Any) -> tuple[str | None, dict[str, Any]]:
    if isinstance(ev, dict):
        return ev.get("event_type"), ev.get("payload") or {}
    return getattr(ev, "event_type", None), getattr(ev, "payload", None) or {}


def chronicle_entries(
    events: Iterable[Any], *, viewer: str | None = None
) -> list[ChronicleEntry]:
    entries: list[ChronicleEntry] = []
    for ev in events:
        etype, payload = _type_payload(ev)
        if etype != EVENT_WORLD_CHRONICLE:
            continue
        present = tuple(str(n) for n in payload.get("present", []) if n)
        # 角色视角只保留自己 present 的段落：空名单意味着「当时没有角色在场」，
        # 对任何 viewer 都不可见（全知/staff 视图不走这条过滤）。
        if viewer is not None and viewer not in present:
            continue
        text = str(payload.get("text", "")).strip()
        if not text:
            continue
        entries.append(
            ChronicleEntry(
                round=int(payload.get("round", 0) or 0),
                text=text,
                present=present,
                location_key=(
                    str(payload.get("location_key"))
                    if payload.get("location_key")
                    else None
                ),
                covers_event_id=int(payload.get("covers_event_id", 0) or 0),
            )
        )
    return entries


def derive_chronicle(events: Iterable[Any], *, viewer: str | None = None) -> str:
    """拼接编年史增量；`viewer` 非空时只保留该角色在场的段落。"""
    return "\n\n".join(e.text for e in chronicle_entries(events, viewer=viewer))
