"""世界事实（M6 §B6）：事件折叠、私密可见性、投影过滤、角色工具。

机制层知识边界：private 事实只进 audience 角色的视图，**绝不**出现在
公屏消息或时间线里（投影层无 viewer，不能当普通 system 广播）。
"""

from __future__ import annotations

import json
import uuid

from app.domain.agents.tools import build_character_tools
from app.domain.game.event import EVENT_WORLD_FACT, EventStore
from app.domain.game.exploration import WorldState, derive_world
from app.domain.game.world_view import RuntimeWorldView
from app.services.session_projection import project_messages, project_timeline


def _store_with_facts() -> EventStore:
    store = EventStore()
    store.append(
        EVENT_WORLD_FACT,
        {
            "fact_id": "f1",
            "kind": "event",
            "text": "渡口的老槐树被雷劈了。",
            "visibility": "public",
            "audience": [],
        },
        session_id="s1",
    )
    store.append(
        EVENT_WORLD_FACT,
        {
            "fact_id": "f2",
            "kind": "secret",
            "text": "船夫其实是官府的眼线。",
            "visibility": "private",
            "audience": ["乙"],
            "location_key": "harbor",
        },
        session_id="s1",
    )
    return store


def test_derive_world_folds_facts_and_filters_by_viewer():
    world = derive_world(_store_with_facts().active_events())

    assert len(world.facts) == 2
    public = world.facts_for(None)
    assert [f.fact_id for f in public] == ["f1"]

    assert [f.fact_id for f in world.facts_for("乙")] == ["f1", "f2"]
    assert [f.fact_id for f in world.facts_for("甲")] == ["f1"]
    # 私密事实带地点锚（M7 离线 tick 复用）
    assert world.facts[1].location_key == "harbor"


def test_projection_shows_public_fact_but_never_private():
    store = _store_with_facts()

    messages = project_messages(uuid.UUID(int=1), store)
    texts = [m["payload"].get("text", "") for m in messages]

    assert any("老槐树" in t for t in texts)
    assert not any("眼线" in t for t in texts)
    # 私密事实也不进时间线（回溯页同一口径）
    timeline = project_timeline(
        uuid.UUID(int=1),
        store,
        stage="stage3_extending",
        allowed_commands=[],
        max_rollback_steps=100,
    )
    assert not any("眼线" in e.text for e in timeline.entries)
    assert any("老槐树" in e.text for e in timeline.entries)


def test_character_tool_only_returns_visible_facts():
    """工具链路走真实 `RuntimeWorldView`（生产实现写错时用例必须红）。"""
    rt = _runtime_with_facts()

    class _Memory:
        personal_log: list[str] = []
        rejected: list[str] = []

    tools = {
        t.name: t
        for t in build_character_tools(memory=_Memory(), world=RuntimeWorldView(rt, "乙"))
    }
    seen_by_yi = json.loads(tools["view_world_facts"].invoke({}))
    assert {f["text"] for f in seen_by_yi} == {
        "渡口的老槐树被雷劈了。",
        "船夫其实是官府的眼线。",
    }

    tools = {
        t.name: t
        for t in build_character_tools(memory=_Memory(), world=RuntimeWorldView(rt, "甲"))
    }
    seen_by_jia = json.loads(tools["view_world_facts"].invoke({}))
    assert {f["text"] for f in seen_by_jia} == {"渡口的老槐树被雷劈了。"}


def _runtime_with_facts():
    from test_exploration import _make_runtime

    rt = _make_runtime()
    rt._world = derive_world(_store_with_facts().active_events())
    return rt


def test_world_state_members_at():
    state = WorldState(memberships={"loc:harbor": ("丙",)})
    assert state.members_at("loc:harbor") == ("丙",)
    assert state.members_at(None) == ()
