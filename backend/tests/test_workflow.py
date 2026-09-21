"""剧本生成 workflow 骨架测试（issue #28）。

- 纯逻辑路径用 ScriptedWorkflowLLM（按 purpose 路由的确定性假 LLM，
  仅测试用，生产路径不引用）无 key 全绿——测试策略 C。
- 真实 LLM 连通的冒烟：本文件的 key-gated 单节点冒烟 +
  scripts/smoke_workflow.py 完整链路（无 key skip）。
"""

from __future__ import annotations

import json

import pytest

from app.contracts.enums import UsagePurpose
from app.contracts.material import MaterialInput, MaterialSource
from app.contracts.script import ScriptPackage
from app.domain.content.pipeline import ContentPipeline
from app.domain.generation.stage1 import synthesize_script_package
from app.domain.generation.workflow import WorkflowNodes, WorkflowRunner, initial_state
from app.domain.prompts import character_design, collect_materials, divide_events
from app.infrastructure.config import get_settings
from app.infrastructure.errx import Error

MATERIAL_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)

_DOSSIER_JSON = json.dumps(
    {
        "background": "朱自清《背影》式的家庭叙事",
        "era_setting": "民国初年，家道中落的知识分子家庭",
        "character_notes": [
            {"name": "我", "note": "离家买药的青年，回望时落泪"},
            {"name": "母亲", "note": "病中仍叮嘱儿子路上小心"},
        ],
        "plot_summary": "母亲病了；我离家买药；回头看见母亲在门口流泪。",
        "teaching_analysis": ["品味平实白描中的深情"],
    },
    ensure_ascii=False,
)

_DIVISION_JSON = json.dumps(
    {
        "scenes": [
            {
                "title": "冬日启程",
                "participants": ["我", "母亲"],
                "beats": [
                    {
                        "description": "母亲病了，我出门买药",
                        "is_key_event": True,
                        "key_event_order": 1,
                    },
                    {
                        "description": "母亲叮嘱路上小心",
                        "is_key_event": True,
                        "key_event_order": 2,
                    },
                    {
                        "description": "我回头看见母亲在门口流泪",
                        "is_key_event": True,
                        "key_event_order": 3,
                    },
                ],
            }
        ]
    },
    ensure_ascii=False,
)

_PROFILE_JSON = json.dumps(
    {
        "public_background": "文中的儿子，为母买药",
        "personality_traits": ["重情", "孝顺"],
        "speech_style": None,
        "is_player_playable": True,
    },
    ensure_ascii=False,
)


def make_analysis():
    return ContentPipeline().analyze(
        MaterialInput(source=MaterialSource.PASTE, raw_text=MATERIAL_TEXT)
    )


class ScriptedWorkflowLLM:
    """按 purpose 路由的确定性假 LLM（生成 workflow 测试专用，非生产路径）。"""

    def __init__(self, analysis, *, doubter_verdicts=("pass",), division_json=None):
        self.calls: list[str] = []
        self._verdicts = list(doubter_verdicts)
        self._division_json = division_json or _DIVISION_JSON
        self._package_json = synthesize_script_package(analysis).model_dump_json()
        self.divide_prompts: list[str] = []
        self.writing_prompts: list[str] = []

    async def chat(self, messages, *, session_id: str = "", purpose=None):  # noqa: ANN001
        name = getattr(purpose, "value", purpose)
        self.calls.append(name)
        if name == UsagePurpose.COLLECT_MATERIALS.value:
            return _DOSSIER_JSON
        if name == UsagePurpose.DOUBTER.value:
            verdict = self._verdicts.pop(0) if self._verdicts else "pass"
            issues = [] if verdict == "pass" else ["时代背景结论缺少原文依据"]
            return json.dumps({"verdict": verdict, "issues": issues}, ensure_ascii=False)
        if name == UsagePurpose.DIVIDE_EVENTS.value:
            self.divide_prompts.append(messages[0]["content"])
            return self._division_json
        if name == UsagePurpose.CHARACTER_DESIGN.value:
            return _PROFILE_JSON
        if name in (UsagePurpose.STAGE1.value, UsagePurpose.SCRIPT_WRITING.value):
            self.writing_prompts.append(messages[0]["content"])
            return self._package_json
        raise AssertionError(f"unexpected purpose: {name}")


def _make_runner(analysis, llm, *, sink=None, gate=False, checkpointer=None):
    from langgraph.checkpoint.memory import MemorySaver

    nodes = WorkflowNodes(llm, teacher_gates=gate)
    runner = WorkflowRunner(
        nodes, checkpointer=checkpointer or MemorySaver(), progress_sink=sink
    )
    state = initial_state(
        script_id=1,
        session_id="test-workflow",
        analysis=analysis,
        web_evidence=[],
    )
    return runner, state


_GATE_SEQUENCE = ("materials", "pre_write", "final")


async def _pause_at(
    analysis, llm, checkpointer, thread_id: str, target: str
):
    """跑到指定闸门：初始 run 停在 materials，再逐闸空恢复到 target。"""
    runner, state = _make_runner(analysis, llm, gate=True, checkpointer=checkpointer)
    await runner.run(state, thread_id=thread_id)
    for gate in _GATE_SEQUENCE[: _GATE_SEQUENCE.index(target)]:
        runner = WorkflowRunner(
            WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
        )
        await runner.resume(thread_id=thread_id, resume_payload={"directives": []}, gate=gate)
    return runner


async def test_materials_gate_pauses_before_divide() -> None:
    """教师闸门（#34）：素材考证通过后暂停在 awaiting_review，划分未开始。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    runner, state = _make_runner(analysis, llm, gate=True)
    final = await runner.run(state, thread_id="t-gate")

    assert final.get("package") is None
    assert runner.snapshot().status == "awaiting_review"
    assert UsagePurpose.DIVIDE_EVENTS.value not in llm.calls
    statuses = {n.node.value: n.status for n in runner.snapshot().nodes}
    assert statuses["collect_materials"] == "succeeded"
    assert statuses["verify_materials"] == "succeeded"
    assert statuses["divide_events"] == "pending"


async def test_materials_gate_resume_carries_directives() -> None:
    """教师恢复：指令经闸门并入 state，下游划分 prompt 可感知（#34 指导语义）。

    闸门是链式的：素材闸恢复后继续跑到中段闸（人物+场景审定）再停。
    """
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    runner, state = _make_runner(analysis, llm, gate=True, checkpointer=checkpointer)
    await runner.run(state, thread_id="t-resume")

    directives = ["母亲的背影要更突出"]
    resumed = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    final = await resumed.resume(
        thread_id="t-resume",
        resume_payload={"directives": directives},
        gate="materials",
    )

    assert final.get("package") is None  # 链式闸门：停在 pre_write 等下一轮审阅
    assert final["directives"] == directives
    assert any(directives[0] in p for p in llm.divide_prompts)
    assert resumed.snapshot().status == "awaiting_review"
    assert resumed.review["gate"] == "pre_write"

    approved = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    final = await approved.resume(
        thread_id="t-resume", resume_payload={"directives": []}, gate="pre_write"
    )
    assert final["package"] is not None
    # #34 指导语义：指令同样到达剧本书写节点（下游 agent 可感知）
    assert any(directives[0] in p for p in llm.writing_prompts)
    assert approved.snapshot().status == "awaiting_review"  # 终审闸门再停
    assert approved.review["gate"] == "final"


async def test_materials_gate_resume_with_dossier_edit() -> None:
    """#34 编辑语义：教师改后的 dossier 覆盖通道，下游书写以编辑稿为准。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    runner, state = _make_runner(analysis, llm, gate=True, checkpointer=checkpointer)
    await runner.run(state, thread_id="t-edit")

    # 闸门审阅载荷：素材快照可展示（materials gate）
    assert runner.review is not None
    assert runner.review["gate"] == "materials"
    assert runner.review["dossier"]["background"].startswith("朱自清")

    edited_background = "教师修订后的背景结论"
    dossier_edit = json.loads(_DOSSIER_JSON)
    dossier_edit["background"] = edited_background
    resumed = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    await resumed.resume(
        thread_id="t-edit",
        resume_payload={"edits": {"dossier": dossier_edit}},
        gate="materials",
    )
    # 逐闸空恢复直到书写（编辑稿沿通道传给下游）
    for gate in ("pre_write", "final"):
        resumed = WorkflowRunner(
            WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
        )
        await resumed.resume(thread_id="t-edit", resume_payload={"directives": []}, gate=gate)

    # 编辑稿进入剧本书写节点的上下文（写作 prompt 含教师修订文本）
    assert any(edited_background in p for p in llm.writing_prompts)


async def test_materials_gate_resume_without_directives_proceeds() -> None:
    """教师逐闸直接恢复：三道闸全空载荷，最终正常产出剧本。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    runner, state = _make_runner(analysis, llm, gate=True, checkpointer=checkpointer)
    await runner.run(state, thread_id="t-resume-empty")

    for gate in _GATE_SEQUENCE:
        runner = WorkflowRunner(
            WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
        )
        final = await runner.resume(
            thread_id="t-resume-empty", resume_payload={"directives": []}, gate=gate
        )
    assert final["package"] is not None
    assert runner.snapshot().status == "succeeded"


async def test_pre_write_gate_pauses_and_review_carries_artifacts() -> None:
    """#34 中段闸门：逐闸恢复到中段后停，审阅载荷带 division+profiles。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    runner = await _pause_at(analysis, llm, checkpointer, "t-pre-write", "pre_write")

    assert UsagePurpose.SCRIPT_WRITING.value not in llm.calls
    assert runner.review is not None
    assert runner.review["gate"] == "pre_write"
    assert runner.review["division"]["scenes"][0]["title"] == "冬日启程"
    assert sorted(p["name"] for p in runner.review["profiles"]) == ["我", "母亲"]
    statuses = {n.node.value: n.status for n in runner.snapshot().nodes}
    assert statuses["divide_events"] == "succeeded"
    assert statuses["design_characters"] == "succeeded"
    assert statuses["write_script"] == "pending"


async def test_pre_write_gate_resume_applies_edits() -> None:
    """#34 中段闸门恢复：教师编辑人物形象/场景名覆盖通道并进入书写。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    await _pause_at(analysis, llm, checkpointer, "t-pre-write-edit", "pre_write")

    division_edit = json.loads(_DIVISION_JSON)
    division_edit["scenes"][0]["title"] = "雪夜启程"
    profiles_edit = json.loads(_PROFILE_JSON)
    profiles_edit["name"] = "我"
    profiles_edit["speech_style"] = "教师修订的语言风格"

    resumed = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    final = await resumed.resume(
        thread_id="t-pre-write-edit",
        resume_payload={
            "edits": {
                "division": division_edit,
                "profiles": [profiles_edit],
            }
        },
        gate="pre_write",
    )

    assert any("雪夜启程" in p for p in llm.writing_prompts)
    assert any("教师修订的语言风格" in p for p in llm.writing_prompts)
    assert final["merged_profiles"][0].speech_style == "教师修订的语言风格"
    # 编辑恢复后继续跑到终审闸门再停（链式）
    assert resumed.snapshot().status == "awaiting_review"
    assert resumed.review["gate"] == "final"


async def test_final_gate_approve_with_package_edit() -> None:
    """#34 终审闸门：逐闸恢复到终审；教师编辑剧本标题后通过 → 编辑稿生效。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    runner = await _pause_at(analysis, llm, checkpointer, "t-final", "final")

    assert runner.review is not None
    assert runner.review["gate"] == "final"
    assert runner.review["package"] is not None

    package_edit = json.loads(json.dumps(runner.review["package"]))
    package_edit["title"] = "教师修订的标题"

    resumed = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    final = await resumed.resume(
        thread_id="t-final",
        resume_payload={"edits": {"package": package_edit}, "action": "approve"},
        gate="final",
    )

    assert final["package"].title == "教师修订的标题"
    assert final["gate_action"] == "approve"
    assert resumed.snapshot().status == "succeeded"


async def test_final_gate_reject_with_package_edit_keeps_edits() -> None:
    """#34 终审打回 + 编辑：教师编辑稿作为重写基线进入书写上下文。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis, doubter_verdicts=("pass", "pass", "pass"))
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    runner = await _pause_at(analysis, llm, checkpointer, "t-final-edit-reject", "final")

    package_edit = json.loads(json.dumps(runner.review["package"]))
    package_edit["title"] = "打回前教师修订的标题"

    resumed = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    await resumed.resume(
        thread_id="t-final-edit-reject",
        resume_payload={
            "directives": ["结尾要落在母亲转身之后"],
            "edits": {"package": package_edit},
            "action": "reject",
        },
        gate="final",
    )

    # 重写以教师编辑稿为基线：编辑文本进入书写 prompt，不被静默丢弃
    assert any("打回前教师修订的标题" in p for p in llm.writing_prompts)
    assert any("结尾要落在母亲转身之后" in p for p in llm.writing_prompts)
    assert resumed.snapshot().status == "awaiting_review"
    assert resumed.review["gate"] == "final"


async def test_final_gate_reject_reruns_writing_then_approves() -> None:
    """#34 终审打回：指导作为打回意见回到书写重做一轮，再次终审通过。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis, doubter_verdicts=("pass", "pass", "pass"))
    from langgraph.checkpoint.memory import MemorySaver

    checkpointer = MemorySaver()
    await _pause_at(analysis, llm, checkpointer, "t-final-reject", "final")

    resumed = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    directive = "结尾要落在母亲转身之后"
    await resumed.resume(
        thread_id="t-final-reject",
        resume_payload={"directives": [directive], "action": "reject"},
        gate="final",
    )

    # 打回后重写一轮，再次停在终审闸门
    assert llm.calls.count(UsagePurpose.SCRIPT_WRITING.value) == 2
    assert resumed.snapshot().status == "awaiting_review"
    assert resumed.review["gate"] == "final"
    assert any(directive in p for p in llm.writing_prompts)

    approved = WorkflowRunner(
        WorkflowNodes(llm, teacher_gates=True), checkpointer=checkpointer
    )
    final = await approved.resume(
        thread_id="t-final-reject",
        resume_payload={"action": "approve"},
        gate="final",
    )
    assert final["package"] is not None
    assert approved.snapshot().status == "succeeded"


async def test_workflow_end_to_end_with_scripted_llm() -> None:
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    runner, state = _make_runner(analysis, llm)
    final = await runner.run(state, thread_id="t-e2e")

    assert isinstance(final["package"], ScriptPackage)
    assert len(final["merged_profiles"]) == 2  # MATERIAL_TEXT 分析出 2 个人物
    snap = runner.snapshot()
    assert snap.status == "succeeded"
    assert all(n.status == "succeeded" for n in snap.nodes)
    assert [e.verdict for e in snap.doubter_events] == ["pass", "pass"]  # 验证 + 总审各记一条
    # 节点用细分 purpose 调用，人物设定并行 fan-out 到每个人物；write 走 script_writing
    assert UsagePurpose.COLLECT_MATERIALS.value in llm.calls
    assert UsagePurpose.DIVIDE_EVENTS.value in llm.calls
    assert UsagePurpose.SCRIPT_WRITING.value in llm.calls
    assert UsagePurpose.STAGE1.value not in llm.calls  # S4：write_script 不再记 stage1
    assert llm.calls.count(UsagePurpose.CHARACTER_DESIGN.value) == 2


async def test_doubter_reject_then_pass_reruns_collection() -> None:
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis, doubter_verdicts=("reject", "pass"))
    runner, state = _make_runner(analysis, llm)
    await runner.run(state, thread_id="t-reject")

    assert llm.calls.count(UsagePurpose.COLLECT_MATERIALS.value) == 2
    events = runner.snapshot().doubter_events
    # verify 节点 reject→pass 各记一条；总审再记一条 pass
    assert [e.verdict for e in events] == ["reject", "pass", "pass"]
    assert events[0].issues == ["时代背景结论缺少原文依据"]
    assert runner.snapshot().status == "succeeded"


async def test_audit_reject_then_pass_reruns_writing() -> None:
    """总审打回 → 书写重做 → 通过（S1/S6 风险路径）。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis, doubter_verdicts=("pass", "reject", "pass"))
    runner, state = _make_runner(analysis, llm)
    final = await runner.run(state, thread_id="t-audit-reject")

    assert final["package"] is not None
    assert llm.calls.count(UsagePurpose.SCRIPT_WRITING.value) == 2  # 打回后重写一次
    events = runner.snapshot().doubter_events
    assert [e.verdict for e in events] == ["pass", "reject", "pass"]
    assert events[1].round == 1  # 首轮书写被打回
    assert runner.snapshot().status == "succeeded"


async def test_audit_exhaustion_fails_within_contract_rounds() -> None:
    """三次打回耗尽即失败；DoubterEvent.round 不超契约上限（le=3，S1）。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(
        analysis, doubter_verdicts=("pass", "reject", "reject", "reject")
    )
    runner, state = _make_runner(analysis, llm)
    with pytest.raises(Error):
        await runner.run(state, thread_id="t-audit-exhaust")
    audit_rounds = [
        e.round for e in runner.snapshot().doubter_events if e.node.value == "final_audit"
    ]
    assert audit_rounds == [1, 2, 3]


async def test_doubter_exhaustion_fails_the_attempt() -> None:
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis, doubter_verdicts=("reject", "reject", "reject"))
    runner, state = _make_runner(analysis, llm)
    with pytest.raises(Error):
        await runner.run(state, thread_id="t-exhaust")


async def test_invalid_division_is_rejected_by_machine_check() -> None:
    analysis = make_analysis()
    bad_division = json.loads(_DIVISION_JSON)
    bad_division["scenes"][0]["beats"][0]["key_event_order"] = 99
    llm = ScriptedWorkflowLLM(
        analysis, division_json=json.dumps(bad_division, ensure_ascii=False)
    )
    runner, state = _make_runner(analysis, llm)
    with pytest.raises(Error):
        await runner.run(state, thread_id="t-bad-division")


async def test_progress_sink_receives_node_events() -> None:
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    snapshots: list = []
    runner, state = _make_runner(
        analysis, llm, sink=lambda s: _collect(snapshots, s)
    )
    await runner.run(state, thread_id="t-sink")

    assert snapshots
    final = snapshots[-1]
    statuses = {n.node.value: n.status for n in final.nodes}
    assert statuses["collect_materials"] == "succeeded"
    assert statuses["design_characters"] == "succeeded"
    assert any(n.node.value == "design_characters" and n.detail for n in final.nodes)


async def test_node_inner_progress_flushes_live_detail() -> None:
    """节点内子进度（progress_hook→on_step）会在执行中即时落快照，不等到节点完成。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    snapshots: list = []
    runner, state = _make_runner(
        analysis, llm, sink=lambda s: _collect(snapshots, s)
    )
    await runner.run(state, thread_id="t-inner")

    # write_script 执行中应有 running + 距今 detail 的快照（起草第 N 轮等）
    seen = [
        n.detail
        for s in snapshots
        for n in s.nodes
        if n.node.value == "write_script" and n.status == "running" and n.detail
    ]
    assert seen, "write_script 执行中应推送带子进度的快照"
    assert any("起草" in d for d in seen)
    final = snapshots[-1]
    ws = next(n for n in final.nodes if n.node.value == "write_script")
    assert ws.status == "succeeded"


async def _collect(snapshots, snapshot) -> None:
    snapshots.append(snapshot)


def test_prompts_embed_prompt_version() -> None:
    analysis = make_analysis()
    assert collect_materials.PROMPT_VERSION in collect_materials.build_user_message(
        analysis, []
    )
    assert divide_events.PROMPT_VERSION in divide_events.build_user_message(analysis, "{}")
    assert character_design.PROMPT_VERSION in character_design.build_user_message(
        name="我", original_traits="", dossier_json="{}"
    )


@pytest.mark.skipif(
    not get_settings().llm_api_key,
    reason="真实 LLM 冒烟需要 WENJING_LLM_API_KEY（测试策略 C：key-gated）",
)
async def test_collect_materials_real_llm_smoke() -> None:
    """有 key 时对单个节点做真实连通冒烟（完整链路见 scripts/smoke_workflow.py）。"""
    from app.infrastructure.config import get_settings
    from app.infrastructure.llm.factory import ModelServiceFactory

    settings = get_settings()
    llm = ModelServiceFactory.build(settings.llm_model_config())
    analysis = make_analysis()
    nodes = WorkflowNodes(llm, model_name=settings.llm_model)
    state = initial_state(
        script_id=1,
        session_id="smoke",
        analysis=analysis,
        web_evidence=[],
    )
    result = await nodes.collect_materials(state)
    assert result["dossier"].background
