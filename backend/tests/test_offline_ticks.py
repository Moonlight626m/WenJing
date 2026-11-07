"""离线 tick（M7 §B6）：确定性计划、tick id、事实/提示载荷、运行时自主行动。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from conftest import FakeLLMService
from test_exploration import _events, _make_runtime, _to_stage3

from app.domain.game.event import EVENT_CHARACTER_SPEECH, EVENT_PROPOSAL, EVENT_WORLD_FACT
from app.domain.game.offline_ticks import (
    MAX_OFFLINE_TICKS,
    npc_action_fact,
    offline_hint_payload,
    plan_offline_ticks,
    tick_id_for,
)

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)


# ===== 1. 计划函数（零 LLM，纯函数）=====


def test_plan_ticks_counts_intervals():
    assert plan_offline_ticks(
        now=NOW, last_at=NOW - timedelta(minutes=59), interval_minutes=30
    ) == 1
    assert plan_offline_ticks(
        now=NOW, last_at=NOW - timedelta(minutes=61), interval_minutes=30
    ) == 2


def test_plan_ticks_clamps_to_max():
    assert plan_offline_ticks(
        now=NOW, last_at=NOW - timedelta(days=7), interval_minutes=30
    ) == MAX_OFFLINE_TICKS


def test_plan_ticks_no_schedule_or_backwards():
    assert plan_offline_ticks(now=NOW, last_at=None, interval_minutes=30) == 0
    assert plan_offline_ticks(now=NOW, last_at=NOW, interval_minutes=30) == 0
    assert plan_offline_ticks(
        now=NOW, last_at=NOW + timedelta(minutes=5), interval_minutes=30
    ) == 0
    # 间隔 ≤0 = 显式关闭离线 tick
    assert plan_offline_ticks(
        now=NOW, last_at=NOW - timedelta(days=1), interval_minutes=0
    ) == 0


def test_tick_id_is_stable_and_index_scoped():
    sid = uuid.UUID(int=42)
    first = tick_id_for(sid, 1)
    assert first == tick_id_for(sid, 1)
    assert first != tick_id_for(sid, 2)
    assert first != tick_id_for(uuid.UUID(int=43), 1)


def test_fact_and_hint_payloads():
    fact = npc_action_fact(
        tick_id="t1", index=2, actor="乙", description="把船绳系紧", location_key="harbor"
    )
    assert fact["fact_id"] == "t1:2"
    assert fact["visibility"] == "public"
    assert fact["kind"] == "npc_action"
    assert fact["text"] == "乙：把船绳系紧"

    hint = offline_hint_payload(ticks=["t1", "t2"], facts=3)
    assert "3 件事" in hint["text"] and hint["ticks"] == ["t1", "t2"]
    quiet = offline_hint_payload(ticks=["t1"], facts=0)
    assert "安静" in quiet["text"]


# ===== 2. 运行时离线 tick：在场 NPC 自主行动 → world_fact =====


async def test_offline_tick_writes_public_facts_and_keeps_round_budget():
    rt = _make_runtime()
    result = await _to_stage3(rt)
    before_rounds = result.state["stage3_round_taken"]
    before_interaction = rt.active_interaction
    proposals_before = len(_events(rt, EVENT_PROPOSAL))

    facts = await rt.offline_tick(tick_id="tick-1")

    # 全体 cast 自主行动（在场与否都算，§B6），事实锚在各自所在地点
    assert facts == 2
    world_facts = _events(rt, EVENT_WORLD_FACT)
    assert {f["text"] for f in world_facts} == {"乙：我提议质询对方", "丙：我提议质询对方"}
    assert {f["location_key"] for f in world_facts} == {"harbor", "inn"}
    assert {f["tick_id"] for f in world_facts} == {"tick-1"}
    # §B6：不设计玩家选项、不跑导演、不判目标、不推进回合
    assert rt.state.stage3_round_taken == before_rounds
    assert rt.active_interaction is before_interaction
    # 提议/验证事件与实时路径同形（重放折叠记忆依赖它）
    assert len(_events(rt, EVENT_PROPOSAL)) == proposals_before + 2


async def test_offline_tick_respects_verifier_rejections():
    rt = _make_runtime(llm=FakeLLMService(verifier_output="reject"))
    await _to_stage3(rt)

    facts = await rt.offline_tick(tick_id="tick-1")

    # 全部被驳回 → 没有世界事实（也可能补一次重提，仍被驳回）
    assert facts == 0
    assert not _events(rt, EVENT_WORLD_FACT)


async def test_offline_tick_noop_outside_stage3():
    rt = _make_runtime()
    await rt.start()
    assert await rt.offline_tick(tick_id="tick-0") == 0
    assert not _events(rt, EVENT_WORLD_FACT)


async def test_offline_tick_does_not_speak():
    """离线 tick 只结转 world_fact，不产生公开台词（不写 player-facing speech）。"""
    rt = _make_runtime()
    await _to_stage3(rt)
    await rt.offline_tick(tick_id="tick-1")
    assert not _events(rt, EVENT_CHARACTER_SPEECH)
