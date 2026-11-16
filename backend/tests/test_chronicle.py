"""编年史（world_chronicle）：增量拼接、限知过滤、运行时每轮写入。"""

from __future__ import annotations

from test_exploration import _events, _make_runtime, _to_stage3

from app.domain.game.chronicle import derive_chronicle
from app.domain.game.event import EVENT_WORLD_CHRONICLE, EventStore


def _store() -> EventStore:
    store = EventStore()
    store.append(
        EVENT_WORLD_CHRONICLE,
        {
            "round": 1,
            "text": "渡口起风了，乙把船绳收紧。",
            "present": ["乙"],
            "location_key": "harbor",
            "covers_event_id": 1,
        },
        session_id="s1",
    )
    store.append(
        EVENT_WORLD_CHRONICLE,
        {
            "round": 2,
            "text": "客栈里，丙听见了门外的脚步。",
            "present": ["丙"],
            "location_key": "inn",
            "covers_event_id": 2,
        },
        session_id="s1",
    )
    return store


def test_derive_chronicle_full_view():
    assert derive_chronicle(_store().active_events()) == (
        "渡口起风了，乙把船绳收紧。\n\n客栈里，丙听见了门外的脚步。"
    )


def test_derive_chronicle_is_viewer_limited():
    events = _store().active_events()
    assert derive_chronicle(events, viewer="乙") == "渡口起风了，乙把船绳收紧。"
    assert derive_chronicle(events, viewer="丙") == "客栈里，丙听见了门外的脚步。"
    assert derive_chronicle(events, viewer="甲") == ""


def test_empty_present_is_not_visible_to_any_character():
    """空在场名单 = 当时没有角色在场；只对全知/staff 可见。"""
    store = EventStore()
    store.append(
        EVENT_WORLD_CHRONICLE,
        {
            "round": 1,
            "text": "无人的渡口，风吹过空船。",
            "present": [],
            "location_key": "harbor",
            "covers_event_id": 1,
        },
        session_id="s1",
    )
    events = store.active_events()
    assert derive_chronicle(events) == "无人的渡口，风吹过空船。"
    assert derive_chronicle(events, viewer="乙") == ""


async def test_stage3_entry_does_not_chronicle_stage2_replay():
    """第一段编年史从进入续写起算，不能把课文重演再写一遍。"""
    rt = _make_runtime()
    await _to_stage3(rt)
    assert _events(rt, EVENT_WORLD_CHRONICLE) == []


async def test_stage3_round_writes_incremental_chronicle():
    rt = _make_runtime()
    await _to_stage3(rt)

    before = len(_events(rt, EVENT_WORLD_CHRONICLE))
    await rt.submit(command_id="c-act", kind="choose_option", payload={"option_id": "0"})
    chronicles = _events(rt, EVENT_WORLD_CHRONICLE)

    assert len(chronicles) == before + 1
    entry = chronicles[-1]
    assert entry["text"].strip()
    assert entry["present"]
    assert entry["covers_event_id"] > 0
    assert entry["location_key"] == "harbor"

    # 下一轮只记录新事件，不重写上一段
    await rt.submit(command_id="c-act-2", kind="choose_option", payload={"option_id": "0"})
    latest = _events(rt, EVENT_WORLD_CHRONICLE)[-1]
    assert latest["round"] >= entry["round"]
    assert latest["covers_event_id"] > entry["covers_event_id"]
