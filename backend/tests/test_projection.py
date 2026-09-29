"""契约投影与剧本转换测试（#5 接缝①③的纯单元部分，无 DB 依赖）。"""

from __future__ import annotations

import uuid

from app.contracts.runtime import RuntimeUpdate
from app.domain.game.script_adapter import script_package_to_script
from app.services.session_projection import project_state, project_update

_SID = uuid.UUID("0d3f5a7b-9c8e-4f12-a3b4-c5d6e7f80910")


def test_script_package_to_script_maps_engine_fields():
    from app.contracts.script import (
        Beat,
        CharacterProfile,
        Scene,
        ScriptPackage,
    )

    pkg = ScriptPackage(
        title="背影",
        characters=[
            CharacterProfile(
                name="父亲",
                public_background="中年父亲",
                is_player_playable={"value": False, "reason": ""},
            ),
            CharacterProfile(
                name="儿子",
                public_background="二十岁青年",
                is_player_playable={"value": True, "reason": "戏份适中"},
            ),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="浦口送别",
                participants=["父亲", "儿子"],
                beats=[
                    Beat(beat_id=1, description="父亲送行"),
                    Beat(beat_id=2, description="买橘子"),
                ],
            )
        ],
        teaching_focus=["白描手法"],
        playable_roles=["儿子"],
        stage2_ending_beat_id=2,
    )
    script = script_package_to_script(pkg)
    assert script.title == "背影"
    assert [c.name for c in script.characters] == ["父亲", "儿子"]
    # playable_roles 是可扮演的权威来源
    assert [c.is_player_playable for c in script.characters] == [False, True]
    assert script.scenes[0].beats[1].description == "买橘子"
    assert script.stage2_ending_beat_id == 2


async def test_project_update_from_runtime_step(make_runtime):
    """StepResult/export_state → RuntimeUpdate：契约可往返、UUID/sequence 确定性。"""
    rt = make_runtime(session_id=str(_SID))
    await rt.start()
    result = await rt.submit(
        command_id="c1", kind="select_role", payload={"role_name": "李白"}
    )

    update = project_update(_SID, rt.event_store, result)
    dumped = update.model_dump(mode="json")
    again = RuntimeUpdate.model_validate(dumped)
    assert again == update

    assert update.session_id == _SID
    assert update.state.stage.value == "stage2_reenacting"
    assert update.state.plot_context["player_role"] == "李白"
    assert update.new_events, "新命令应产生事件引用"
    # 确定性：同一事件重复投影得到同一 UUID
    ev = update.new_events[0]
    dup = project_update(_SID, rt.event_store, result).new_events[0]
    assert ev.event_id == dup.event_id
    assert ev.sequence == dup.sequence


async def test_project_state_attributes(make_runtime):
    rt = make_runtime(session_id=str(_SID))
    await rt.start()
    export = rt.export_state()
    state = project_state(_SID, rt.event_store, export)
    assert state.stage.value == "stage1_complete"
    assert state.last_sequence == len(rt.event_store.active_events()) - 1
    assert state.active_interaction is None  # stage1 停靠点无交互
    assert isinstance(state.character_memories, dict)


async def test_project_interaction_options(make_runtime):
    rt = make_runtime(session_id=str(_SID))
    await rt.start()
    await rt.submit(command_id="c1", kind="select_role", payload={"role_name": "李白"})
    export = rt.export_state()
    state = project_state(_SID, rt.event_store, export)
    ix = state.active_interaction
    assert ix is not None
    assert ix.mode.value == "options"
    assert ix.options, "交互点应带选项"
    assert all(o.option_id and o.label for o in ix.options)


# ===== #53 scene_key / current_asset 投影与重放 =====


def _bg():
    from app.contracts.script import AssetRef

    return AssetRef(asset_id=uuid.uuid4(), kind="background", status="ready")


def _attach_backgrounds(rt, bg1, bg2) -> None:
    """给前两个场景挂背景（测试剧本两场景；无 DB，直接挂引擎 script）。"""
    rt.script.scenes[0].background_asset = bg1
    rt.script.scenes[1].background_asset = bg2


async def _start_and_select(rt) -> None:
    """start + 选角（走真实命令路径）：推进到第 1 拍。"""
    await rt.start()
    await rt.submit(command_id="c0", kind="select_role", payload={"role_name": "李白"})


async def _choose(rt, *option_ids: int) -> None:
    """继续推进若干拍（每次 choose_option 播一拍）。命令 id 用随机 UUID 防重放命中。"""
    for opt in option_ids:
        await rt.submit(
            command_id=str(uuid.uuid4()),
            kind="choose_option",
            payload={"option_id": str(opt)},
        )


async def test_project_state_scene_key_and_asset_follow_commands(make_runtime):
    """验收「切场景背景变化」：经命令路径推进，跨场景时 scene_key 与
    current_asset 在投影状态里同步换到新场景。"""
    rt = make_runtime(session_id=str(_SID))
    bg1, bg2 = _bg(), _bg()
    _attach_backgrounds(rt, bg1, bg2)

    await _start_and_select(rt)  # 播第 1 拍（场景1）
    s1 = project_state(_SID, rt.event_store, rt.export_state())
    assert s1.scene_key == "scene:1"
    assert s1.scene_id == 1
    assert s1.scene_title == "相遇"
    assert s1.current_asset is not None and s1.current_asset.asset_id == bg1.asset_id

    # 再推两拍跨入场景2（场景1 两拍：beat1、beat2）
    await _choose(rt, 1, 1)
    s2 = project_state(_SID, rt.event_store, rt.export_state())
    assert s2.scene_key == "scene:2"
    assert s2.scene_id == 2
    assert s2.scene_title == "送别"
    assert s2.current_asset is not None
    assert s2.current_asset.asset_id == bg2.asset_id, "跨场景后背景换图"


async def test_no_current_scene_before_first_beat(make_runtime):
    """开播前（游标 0）没有「当前场景」：scene_key 与 current_asset 同为 None。

    （避免「有背景却无场景键」的字段互斥——两字段推导规则必须一致）
    """
    rt = make_runtime(session_id=str(_SID))
    bg1, bg2 = _bg(), _bg()
    _attach_backgrounds(rt, bg1, bg2)

    await rt.start()  # 停在 stage1_complete，尚未播任何拍
    state = project_state(_SID, rt.event_store, rt.export_state())
    assert state.beat_cursor == 0
    assert state.scene_key is None
    assert state.scene_title is None
    assert state.current_asset is None


async def test_replay_rebuilds_scene_key_without_snapshot_key(make_runtime):
    """验收「重放不丢背景」：快照**不含** scene_key 时，靠事件 payload 重建
    （真正覆盖 `_replay_event` 的重建分支——快照已带 key 的用例覆盖不到它）。"""
    rt = make_runtime(session_id=str(_SID))
    bg1, bg2 = _bg(), _bg()
    _attach_backgrounds(rt, bg1, bg2)
    await _start_and_select(rt)
    await _choose(rt, 1, 1)  # 推进到场景2

    snapshot = rt.export_state()
    assert snapshot["scene_key"] == "scene:2"
    del snapshot["scene_key"]  # 模拟不含该字段的旧快照

    rt2 = make_runtime(session_id=str(_SID))
    _attach_backgrounds(rt2, bg1, bg2)
    rt2.replay_from(snapshot, [e.to_dict() for e in rt.event_store.active_events()])

    assert rt2.state.scene_key == "scene:2", "由 plot_advancement payload 重建"
    state = project_state(_SID, rt2.event_store, rt2.export_state())
    assert state.scene_key == "scene:2"
    assert state.current_asset is not None
    assert state.current_asset.asset_id == bg2.asset_id, "重放后背景不丢"


async def test_replay_legacy_events_without_scene_key_payload(make_runtime):
    """旧事件流（payload 无 scene_key）重放不炸：scene_key 保持 None（向后兼容）。"""
    rt = make_runtime(session_id=str(_SID))
    bg1, bg2 = _bg(), _bg()
    _attach_backgrounds(rt, bg1, bg2)
    await _start_and_select(rt)
    await _choose(rt, 1)

    legacy = [
        {
            **e.to_dict(),
            "payload": {
                k: v
                for k, v in (e.payload or {}).items()
                if k not in ("scene_key", "scene_title", "current_asset")
            },
        }
        for e in rt.event_store.active_events()
        if e.event_type == "plot_advancement"
    ]
    assert legacy, "前置：应有 plot_advancement 事件"

    rt2 = make_runtime(session_id=str(_SID))
    _attach_backgrounds(rt2, bg1, bg2)
    rt2.replay_from(None, legacy)  # 无快照、无 scene_key payload

    assert rt2.state.scene_key is None, "旧流无 payload → 保持 None"


async def test_narrative_message_carries_scene_switch_info(make_runtime):
    """实时切场景（验收 2 的真实链路）：narrative WS 消息必须带
    scene_key/scene_title/current_asset——否则前端只能等重连才换图。"""
    from app.services.session_projection import project_messages

    rt = make_runtime(session_id=str(_SID))
    bg1, bg2 = _bg(), _bg()
    _attach_backgrounds(rt, bg1, bg2)
    await _start_and_select(rt)
    await _choose(rt, 1, 1)  # 推进到场景2

    msgs = project_messages(_SID, rt.event_store)
    narratives = [m for m in msgs if m["type"] == "narrative"]
    assert narratives, "应有 narrative 消息"
    # 跨场景那条（第二条 plot_advancement）必须携带新场景信息
    last = narratives[-1]["payload"]
    assert last.get("scene_key") == "scene:2"
    assert last.get("scene_title") == "送别"
    asset = last.get("current_asset")
    assert asset is not None and asset["asset_id"] == str(bg2.asset_id)


async def test_asset_ready_event_is_projected_as_ws_message(make_runtime):
    """#56：`asset_ready` 必须进消息类别表——不进的话事件落了库却永远不推给前端。"""
    from app.services.session_projection import project_messages

    rt = make_runtime(session_id=str(_SID))
    _attach_backgrounds(rt, _bg(), _bg())
    await _start_and_select(rt)

    asset_id = uuid.uuid4()
    rt.event_store.append(
        "asset_ready",
        {
            "scene_key": "scene:1",
            "asset_id": str(asset_id),
            "kind": "background",
            "status": "ready",
        },
    )

    msgs = project_messages(_SID, rt.event_store)
    ready = [m for m in msgs if m["type"] == "asset_ready"]
    assert len(ready) == 1
    assert ready[0]["seq"] == len(rt.event_store.active_events()) - 1
    payload = ready[0]["payload"]
    assert payload["category"] == "asset_ready"
    assert payload["scene_key"] == "scene:1"
    # 与 narrative 消息同形携带 current_asset：前端复用同一套换背景逻辑
    assert payload["current_asset"] == {
        "asset_id": str(asset_id),
        "kind": "background",
        "status": "ready",
    }
    # 不是内容块：不带 text，前端不该把它塞进字幕/消息流
    assert "text" not in payload


async def test_asset_ready_after_seq_is_replayed_on_resync(make_runtime):
    """断线补发（project_messages(after_seq=…)）也要能补出配图消息。"""
    from app.services.session_projection import project_messages

    rt = make_runtime(session_id=str(_SID))
    _attach_backgrounds(rt, _bg(), _bg())
    await _start_and_select(rt)
    before = len(rt.event_store.active_events())

    asset_id = uuid.uuid4()
    rt.event_store.append(
        "asset_ready",
        {"scene_key": "scene:1", "asset_id": str(asset_id)},
    )

    replayed = project_messages(_SID, rt.event_store, after_seq=before - 1)
    assert [m["type"] for m in replayed] == ["asset_ready"]
    # 缺省 kind/status 由投影补齐（事件载荷允许省略，与 derive_scene_assets 同约定）
    assert replayed[0]["payload"]["current_asset"] == {
        "asset_id": str(asset_id),
        "kind": "background",
        "status": "ready",
    }


async def test_asset_ready_updates_current_asset_in_projection(make_runtime):
    """运行期配图进投影 state：前端下一次 render 就能拿到新背景。"""
    from app.services.session_projection import project_update

    rt = make_runtime(session_id=str(_SID))
    _attach_backgrounds(rt, _bg(), _bg())
    await _start_and_select(rt)
    result = None
    for _ in range(4):  # 推进到第 3 拍（场景2）
        result = await rt.submit(
            command_id=str(uuid.uuid4()),
            kind="choose_option",
            payload={"option_id": "1"},
        )
        if result.state["scene_key"] == "scene:2":
            break
    assert result is not None and result.state["scene_key"] == "scene:2"

    runtime_asset = uuid.uuid4()
    rt.event_store.append(
        "asset_ready",
        {"scene_key": "scene:2", "asset_id": str(runtime_asset)},
    )
    result.state = rt.export_state()
    update = project_update(_SID, rt.event_store, result)
    assert update.state.current_asset is not None
    assert update.state.current_asset.asset_id == runtime_asset
