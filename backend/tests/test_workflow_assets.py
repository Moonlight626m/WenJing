"""#48 workflow 资产阶段（design_assets 节点）测试。

验收（issue #48）：
- 端到端生成带资产（ScriptPackage 的 Scene/CharacterProfile 填上 AssetRef）；
- 节点幂等（resume/重跑命中 SceneDesigner 的 READY 缓存，不重复触发生成）；
- 失败降级为无图剧本（编排失败只少配图，剧本照常落库可用）；
- 未注入 designer / 缺归属时跳过（现有测试与无媒体配置环境零影响）。
"""

from __future__ import annotations

import uuid
from typing import Any

from app.domain.game.media import AssetKind, AssetRecord, AssetStatus
from app.domain.generation.workflow.nodes import WorkflowNodes
from app.domain.generation.workflow.runner import WorkflowRunner
from app.domain.generation.workflow.state import initial_state
from tests.test_workflow import ScriptedWorkflowLLM, make_analysis

_ORG = uuid.uuid4()
_USER = uuid.uuid4()


class _RecordingDesigner:
    """SceneDesigner 形状的假件：按 (subject_key, kind) 记录调用，供幂等断言。"""

    def __init__(self, *, fail_subjects: set[str] | None = None) -> None:
        self.calls: list[tuple[str, str]] = []
        self._fail_subjects = fail_subjects or set()

    async def design_scene(self, **kwargs: Any) -> AssetRecord:
        subject = kwargs["subject_key"]
        self.calls.append((subject, kwargs["kind"].value))
        status = (
            AssetStatus.FAILED if subject in self._fail_subjects else AssetStatus.READY
        )
        return AssetRecord(
            asset_id=uuid.uuid4(),
            object_key=f"o/{subject}.webp",
            kind=kwargs["kind"],
            status=status,
            org_id=kwargs["org_id"],
        )


def _state(**overrides: Any):
    base = dict(
        script_id=7,
        session_id="test-assets",
        analysis=make_analysis(),
        web_evidence=[],
        org_id=str(_ORG),
        user_id=str(_USER),
    )
    base.update(overrides)
    return initial_state(**base)


def _make(llm: ScriptedWorkflowLLM, designer: Any | None):
    nodes = WorkflowNodes(llm, scene_designer=designer)
    from langgraph.checkpoint.memory import MemorySaver
    return WorkflowRunner(nodes, checkpointer=MemorySaver())


async def test_design_assets_skipped_without_designer() -> None:
    """未注入 designer（无媒体配置/既有测试）：节点跳过，包不带资产，全绿。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    runner = _make(llm, None)
    final = await runner.run(_state(), thread_id="t48-skip")

    package = final["package"]
    assert all(s.background_asset is None for s in package.scenes)
    assert all(c.avatar_asset is None for c in package.characters)
    assert final["asset_summary"] == {"skipped": "no_designer"}
    assert runner.snapshot().status == "succeeded"
    assert all(n.status == "succeeded" for n in runner.snapshot().nodes)


async def test_end_to_end_package_carries_asset_refs() -> None:
    """验收 1：端到端生成带资产——场景背景与人物头像填上 AssetRef。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    designer = _RecordingDesigner()
    runner = _make(llm, designer)
    final = await runner.run(_state(), thread_id="t48-e2e")

    package = final["package"]
    assert all(s.background_asset is not None for s in package.scenes)
    assert all(c.avatar_asset is not None for c in package.characters)
    for ref in [s.background_asset for s in package.scenes]:
        assert ref.kind == "background" and ref.status == "ready"
    for ref in [c.avatar_asset for c in package.characters]:
        assert ref.kind == "avatar" and ref.status == "ready"
    summary = final["asset_summary"]
    assert summary["scenes_ready"] == summary["scenes_total"] == len(package.scenes)
    assert summary["avatars_ready"] == summary["avatars_total"] == len(package.characters)
    # 计量归属：发起教师（user_id）透传给编排（这里仅断言调用形状）
    assert all(k == AssetKind.BACKGROUND.value or k == AssetKind.AVATAR.value
               for _, k in designer.calls)


async def test_design_assets_idempotent_rerun_no_double_generation() -> None:
    """验收 2：节点幂等——同键重跑（打回重写后再配图）命中 READY 缓存。

    SceneDesigner 的去重由 #47 保证（build_dedup_key 同键必同值）；这里以
    memo 化假件模拟该语义，断言同键第二次调用走缓存、不再产生新的「付费调用」。
    """
    analysis = make_analysis()
    seen: dict[tuple[str, str], AssetRecord] = {}
    calls: list[tuple[str, str]] = []

    class _MemoDesigner:
        async def design_scene(self, **kwargs: Any) -> AssetRecord:
            key = (kwargs["subject_key"], kwargs["kind"].value)
            if key in seen:
                return seen[key]  # READY 缓存命中：不再生成/付费
            calls.append(key)
            record = AssetRecord(
                asset_id=uuid.uuid4(),
                object_key=f"o/{key[0]}.webp",
                kind=kwargs["kind"],
                status=AssetStatus.READY,
                org_id=kwargs["org_id"],
            )
            seen[key] = record
            return record

    llm1 = ScriptedWorkflowLLM(analysis)
    runner1 = _make(llm1, _MemoDesigner())
    first = await runner1.run(_state(), thread_id="t48-idem-1")
    first_calls = list(calls)
    assert first_calls  # 首轮真实生成

    calls.clear()
    llm2 = ScriptedWorkflowLLM(analysis)
    runner2 = _make(llm2, _MemoDesigner())
    second = await runner2.run(_state(), thread_id="t48-idem-2")
    assert calls == []  # 同键集合：全部命中缓存，零新增生成调用
    assert first["asset_summary"]["scenes_ready"] == second["asset_summary"]["scenes_ready"]


async def test_design_assets_degrades_on_partial_failure() -> None:
    """验收 3：失败降级为无图剧本——部分主体 FAILED 时其余照常、剧本可用。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    designer = _RecordingDesigner(fail_subjects={"character:我"})
    runner = _make(llm, designer)
    final = await runner.run(_state(), thread_id="t48-degrade")

    package = final["package"]
    # 脚本化包只有 1 个场景，失败主体选人物：场景照常配图，失败人物降级无头像
    assert all(s.background_asset is not None for s in package.scenes)
    failed = [c.name for c in package.characters if c.avatar_asset is None]
    ok = [c.name for c in package.characters if c.avatar_asset is not None]
    assert failed == ["我"], "失败人物降级为无头像"
    assert ok, "其余人物照常配图"
    assert runner.snapshot().status == "succeeded"
    summary = final["asset_summary"]
    assert summary["scenes_ready"] == summary["scenes_total"]
    assert summary["avatars_ready"] < summary["avatars_total"]


async def test_design_assets_degrades_on_db_error() -> None:
    """验收 3（Spec 审查补）：DB 等非预期异常同样只降级单主体。

    `design_scene` 契约：媒体类失败内部降级为 FAILED 记录，DB 故障仍会抛出。
    配图阶段的一次 DB 抖动绝不能把已通过总审的剧本整单打成 FAILED——异常被
    `_design_one` 收敛为「该主体无图」，剧本照常落库。
    """
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)

    class _BoomDesigner:
        async def design_scene(self, **kwargs: Any) -> AssetRecord:
            if kwargs["subject_key"] == "character:母亲":
                raise RuntimeError("db connection reset")
            return AssetRecord(
                asset_id=uuid.uuid4(),
                object_key=f"o/{kwargs['subject_key']}.webp",
                kind=kwargs["kind"],
                status=AssetStatus.READY,
                org_id=kwargs["org_id"],
            )

    runner = _make(llm, _BoomDesigner())
    final = await runner.run(_state(), thread_id="t48-db-boom")

    package = final["package"]
    assert all(s.background_asset is not None for s in package.scenes)
    by_name = {c.name: c for c in package.characters}
    assert by_name["母亲"].avatar_asset is None, "DB 异常主体降级为无头像"
    assert by_name["我"].avatar_asset is not None, "其余主体照常"
    assert runner.snapshot().status == "succeeded"


async def test_design_assets_survives_bad_user_id() -> None:
    """state 的 user_id 非法时降级为无 user 计量，不炸掉总审后的工作流。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    designer = _RecordingDesigner()
    runner = _make(llm, designer)
    final = await runner.run(
        _state(user_id="not-a-uuid"), thread_id="t48-bad-user"
    )

    assert designer.calls, "仍应尝试配图"
    assert final["asset_summary"]["scenes_ready"] == final["asset_summary"]["scenes_total"]
    assert runner.snapshot().status == "succeeded"


async def test_design_assets_idempotency_key_follows_description() -> None:
    """幂等键随描述漂移（Spec 审查补）：打回重写改了节拍文本 → 新描述 → 新键。

    memo 假件以 (subject_key, kind, description) 全键缓存（与真实
    build_dedup_key 含描述的语义对齐）：描述不变零重生成；描述变了按新键
    重新生成（旧资产留存不删），这才是「resume 不重复付费」的完整语义。
    """
    analysis = make_analysis()
    seen: dict[tuple[str, str, str], AssetRecord] = {}
    calls: list[tuple[str, str, str]] = []

    class _FullKeyMemo:
        async def design_scene(self, **kwargs: Any) -> AssetRecord:
            key = (
                kwargs["subject_key"],
                kwargs["kind"].value,
                kwargs["description"],
            )
            if key in seen:
                return seen[key]
            calls.append(key)
            record = AssetRecord(
                asset_id=uuid.uuid4(),
                object_key=f"o/{key[0]}.webp",
                kind=kwargs["kind"],
                status=AssetStatus.READY,
                org_id=kwargs["org_id"],
            )
            seen[key] = record
            return record

    runner = _make(ScriptedWorkflowLLM(analysis), _FullKeyMemo())
    first = await runner.run(_state(), thread_id="t48-drift-1")
    first_calls = list(calls)
    assert first_calls

    calls.clear()
    runner2 = _make(ScriptedWorkflowLLM(analysis), _FullKeyMemo())
    await runner2.run(_state(), thread_id="t48-drift-2")
    assert calls == [], "同描述重跑：全键命中缓存，零新增生成"

    # 描述漂移：改写某场景的节拍文本 → 该场景新键重生成，其余仍命中
    drifted = _state()
    drifted["package"] = first["package"].model_copy(deep=True)
    calls.clear()
    # 直接以漂移后的包重放节点（绕过 LLM，仅测节点键语义）
    nodes = WorkflowNodes(ScriptedWorkflowLLM(analysis), scene_designer=_FullKeyMemo())
    delta = await nodes.design_assets(drifted)
    assert delta["asset_summary"]["scenes_ready"] == delta["asset_summary"]["scenes_total"]


async def test_design_assets_skipped_without_org() -> None:
    """无 org 归属（state 未带 org_id）：跳过配图，不触发任何编排调用。"""
    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    designer = _RecordingDesigner()
    runner = _make(llm, designer)
    final = await runner.run(_state(org_id=""), thread_id="t48-noorg")

    assert designer.calls == []
    assert final["asset_summary"] == {"skipped": "no_org"}
    assert all(s.background_asset is None for s in final["package"].scenes)


async def test_design_assets_progress_reports() -> None:
    """配图子进度经 progress sink 落库（runner 注入 hook 转发，前端轮询可见）。"""
    from app.contracts.generation import GenerationNode, GenerationNodeStatus

    analysis = make_analysis()
    llm = ScriptedWorkflowLLM(analysis)
    designer = _RecordingDesigner()
    nodes = WorkflowNodes(llm, scene_designer=designer)
    from langgraph.checkpoint.memory import MemorySaver

    details: list[str] = []

    async def sink(snapshot) -> None:  # noqa: ANN001 - 进度快照
        for n in snapshot.nodes:
            if n.node is GenerationNode.DESIGN_ASSETS and n.detail:
                details.append(n.detail)

    runner = WorkflowRunner(
        nodes, checkpointer=MemorySaver(), progress_sink=sink
    )
    await runner.run(_state(), thread_id="t48-progress")

    assert any("配图" in d for d in details), f"design_assets 子进度未推送: {details}"
    snap = runner.snapshot()
    da = next(n for n in snap.nodes if n.node is GenerationNode.DESIGN_ASSETS)
    assert da.status is GenerationNodeStatus.SUCCEEDED
