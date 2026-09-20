"""workflow 节点实现（issue #28 骨架）。

- 节点直接调用现有 `LLMService`（含 UsageRecordingLLM 计量包装），
  不经 LangChain ChatModel——LangGraph 在此只做编排，结构化输出走
  「prompt + JSON 解析 + Pydantic 校验」（research doc §3.5 建议 b）。
- 每个节点的 prompt 来自 app/prompts/（集中模板 + prompt_version）。
- 骨架边界：素材收集单轮（#29 多轮）、doubter 两处复用（#30 框架化）、
  人物并行 Send fan-out（#32 深化合并裁决）、write_script 暂由
  Stage1Generator 承担（#33 退役旧路径）。
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Send

from app.agents.llm_service import LLMService
from app.contracts.content import TextAnalysis
from app.contracts.enums import UsagePurpose
from app.contracts.script import CharacterProfile
from app.errx import codes, new
from app.generation.json_text import extract_json
from app.generation.stage1 import Stage1Generator
from app.generation.workflow.state import WorkflowState
from app.generation.workflow.types import (
    EventDivisionDraft,
    MaterialDossier,
)
from app.prompts import character_design, collect_materials, divide_events, doubter

logger = logging.getLogger("wenjing.generation.workflow")

MAX_DOUBTER_ROUNDS = 2   # doubter 打回上限（沿用 stage1 MAX_RETRIES 心智）
MAX_WRITE_RETRIES = 2    # final_audit 打回剧本书写的上限
MAX_MAIN_CHARACTERS = 4  # 复现层主要人物数（骨架上限；#32 深化筛选）

# 节点内子进度回调：(workflow 节点键, detail 文本)；由 runner 注入，转发给进度 sink
ProgressHook = Callable[[str, str], Awaitable[None]]


class VerdictResult:
    """doubter 裁决解析后的载体（校验在 _parse_verdict 完成）。"""

    __slots__ = ("verdict", "issues")

    def __init__(self, verdict: str, issues: list[str]) -> None:
        self.verdict = verdict
        self.issues = issues


def _parse_verdict(raw: str) -> VerdictResult:
    data = json.loads(extract_json(raw))
    verdict = str(data.get("verdict", "")).strip().lower()
    if verdict not in ("pass", "reject"):
        raise ValueError(f"invalid doubter verdict: {verdict!r}")
    issues = [str(i) for i in data.get("issues", []) if str(i).strip()]
    if verdict == "reject" and not issues:
        raise ValueError("reject verdict requires issues")
    return VerdictResult(verdict, issues)


class WorkflowNodes:
    """节点集合：以 LLM 服务为依赖闭包，供 build_workflow 装配。"""

    def __init__(
        self,
        llm: LLMService,
        *,
        model_name: str = "",
    ) -> None:
        self._llm = llm
        self._model_name = model_name
        self._progress_hook: ProgressHook | None = None

    def set_progress_hook(self, hook: ProgressHook | None) -> None:
        """注入节点内子进度回调（runner 在建图后调用）。"""
        self._progress_hook = hook

    # ===== 工具 =====

    async def _report(self, node: str, detail: str) -> None:
        """向进度 sink 推送节点内子进度（无 hook 时静默）。"""
        if self._progress_hook is not None:
            await self._progress_hook(node, detail)

    async def _chat(self, prompt: str, state: WorkflowState, purpose: UsagePurpose) -> str:
        return await self._llm.chat(
            [{"role": "user", "content": prompt}],
            session_id=state.get("session_id", ""),
            purpose=purpose,
        )

    @staticmethod
    def _analysis_digest(analysis: TextAnalysis) -> str:
        """doubter 的「原文依据摘要」：人物 + 关键事件顺序 + 素材集结论。"""
        lines = [f"标题：{analysis.title or '佚名'}；体裁：{analysis.genre.genre.value}"]
        lines.append("【人物】")
        for c in analysis.characters:
            traits = "、".join(filter(None, [c.role, c.personality])) or ""
            lines.append(f"- {c.name}：{traits}")
        lines.append("【关键事件（按原文顺序）】")
        for ke in sorted(analysis.key_events, key=lambda k: k.order):
            lines.append(f"- 序号 {ke.order}：{ke.title} — {ke.description}")
        return "\n".join(lines)

    @staticmethod
    def _source_digest(state: WorkflowState) -> str:
        parts = [WorkflowNodes._analysis_digest(state["analysis"])]
        dossier = state.get("dossier")
        if dossier is not None:
            parts.append("【素材集结论（已过 doubter）】\n" + dossier.model_dump_json())
        return "\n\n".join(parts)

    # ===== 素材收集 =====

    async def collect_materials(self, state: WorkflowState) -> dict[str, Any]:
        """素材收集（骨架：单轮 LLM 摘要 + 网络资料；#29 升级多轮检索）。"""
        analysis = state["analysis"]
        prompt = collect_materials.build_user_message(
            analysis,
            state.get("web_evidence", []),
            feedback=state.get("doubter_feedback"),
        )
        raw = await self._chat(prompt, state, UsagePurpose.COLLECT_MATERIALS)
        try:
            dossier = MaterialDossier.model_validate_json(extract_json(raw))
        except Exception as exc:
            raise new(
                codes.LLM_OUTPUT_PARSE_FAILED,
                extra={"target": "MaterialDossier", "reason": str(exc)},
            ) from exc
        return {"dossier": dossier, "doubter_feedback": None}

    async def verify_materials(self, state: WorkflowState) -> dict[str, Any]:
        """doubter 质询素材集（骨架复用 doubter.v1；#30 框架化到全节点）。"""
        dossier = state.get("dossier")
        if dossier is None:  # 防御：打回回路丢失产物时直接失败
            raise new(codes.CNT_GENERATION_FAILED, extra={"reason": "dossier missing"})
        prompt = doubter.build_user_message(
            node_name="collect_materials",
            artifact_schema_hint=(
                "MaterialDossier{background, era_setting, character_notes:[{name,note}],"
                " plot_summary, teaching_analysis}"
            ),
            artifact_json=dossier.model_dump_json(),
            source_digest=self._analysis_digest(state["analysis"]),
        )
        raw = await self._chat(prompt, state, UsagePurpose.DOUBTER)
        try:
            verdict = _parse_verdict(raw)
        except ValueError as exc:
            logger.warning(
                "[script-gen][verify_materials] doubter_verdict_parse_failed reason=%s", exc
            )
            verdict = VerdictResult("pass", [])  # doubter 自身输出异常不阻塞主流程
        round_no = state.get("doubter_round", 0) + 1
        return {
            "doubter_verdict": verdict.verdict,
            "doubter_issues": verdict.issues,
            "doubter_round": round_no,
            "doubter_feedback": (
                "；".join(verdict.issues) if verdict.verdict == "reject" else None
            ),
        }

    def route_after_verify(self, state: WorkflowState) -> str:
        verdict = state.get("doubter_verdict", "pass")
        if verdict == "pass":
            return "divide_events"
        if state.get("doubter_round", 0) <= MAX_DOUBTER_ROUNDS:
            return "collect_materials"
        return "fail"

    # ===== 事件/情景划分 =====

    async def divide_events(self, state: WorkflowState) -> dict[str, Any]:
        analysis = state["analysis"]
        dossier = state.get("dossier")
        dossier_json = dossier.model_dump_json() if dossier is not None else "{}"
        prompt = divide_events.build_user_message(
            analysis,
            dossier_json,
            directives=state.get("directives") or [],
        )
        raw = await self._chat(prompt, state, UsagePurpose.DIVIDE_EVENTS)
        try:
            division = EventDivisionDraft.model_validate_json(extract_json(raw))
        except Exception as exc:
            raise new(
                codes.LLM_OUTPUT_PARSE_FAILED,
                extra={"target": "EventDivisionDraft", "reason": str(exc)},
            ) from exc
        self._validate_division(analysis, division)
        return {"division": division}

    @staticmethod
    def _validate_division(analysis: TextAnalysis, division: EventDivisionDraft) -> None:
        """机器校验：关键 beat 的 key_event_order 必须指向真实关键事件。"""
        known_orders = {ke.order for ke in analysis.key_events}
        known_names = {c.name for c in analysis.characters}
        for scene in division.scenes:
            ghosts = [p for p in scene.participants if p not in known_names]
            if ghosts:
                raise new(
                    codes.LLM_OUTPUT_PARSE_FAILED,
                    extra={"target": "EventDivisionDraft", "reason": f"未知人物 {ghosts}"},
                )
            for beat in scene.beats:
                if beat.is_key_event and beat.key_event_order not in known_orders:
                    raise new(
                        codes.LLM_OUTPUT_PARSE_FAILED,
                        extra={
                            "target": "EventDivisionDraft",
                            "reason": f"关键事件序号 {beat.key_event_order} 不存在",
                        },
                    )

    # ===== 人物设定（Send 并行）=====

    def design_characters(self, state: WorkflowState) -> list[Send]:
        """按原文戏份选出主要人物，Send fan-out 并行生成设定（#32 深化）。"""
        analysis = state["analysis"]
        dossier = state.get("dossier")
        dossier_json = dossier.model_dump_json() if dossier is not None else "{}"
        key_participants: dict[str, int] = {}
        for ke in analysis.key_events:
            for name in ke.participants:
                key_participants[name] = key_participants.get(name, 0) + 1
        ranked = sorted(
            analysis.characters,
            key=lambda c: (
                -key_participants.get(c.name, 0),
                -(len(c.evidence_refs) if c.evidence_refs else 0),
                c.name,
            ),
        )
        selected = ranked[:MAX_MAIN_CHARACTERS]
        return [
            Send(
                "design_one_character",
                {
                    "name": c.name,
                    "original_traits": "、".join(filter(None, [c.role, c.personality])),
                    "role_hint": f"参与 {key_participants.get(c.name, 0)} 个关键事件",
                    "dossier_json": dossier_json,
                    "session_id": state.get("session_id", ""),
                },
            )
            for c in selected
        ]

    async def design_one_character(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self._report("design_characters", f"正在设计人物：{payload['name']}")
        prompt = character_design.build_user_message(
            name=payload["name"],
            original_traits=payload.get("original_traits", ""),
            dossier_json=payload.get("dossier_json", "{}"),
            role_hint=payload.get("role_hint", ""),
        )
        raw = await self._llm.chat(
            [{"role": "user", "content": prompt}],
            session_id=payload.get("session_id", ""),
            purpose=UsagePurpose.CHARACTER_DESIGN,
        )
        try:
            data = json.loads(extract_json(raw))
            profile = CharacterProfile(
                name=payload["name"],
                public_background=str(data.get("public_background", "")),
                personality_traits=[str(t) for t in data.get("personality_traits", [])],
                speech_style=data.get("speech_style"),
                is_player_playable=bool(data.get("is_player_playable", False)),
            )
        except Exception as exc:
            raise new(
                codes.LLM_OUTPUT_PARSE_FAILED,
                extra={"target": "CharacterProfile", "reason": str(exc)},
            ) from exc
        return {"character_profiles": [profile]}

    async def merge_characters(self, state: WorkflowState) -> dict[str, Any]:
        """join 节点：把各人物分支产物按名去重归入 merged_profiles。

        取**最后一次**写入（最新一轮 fan-out 覆盖旧轮）——doubter 打回后
        divide_events 会重新 Send，operator.add 通道会残留旧轮产物，
        确定性选人保证各轮人物名一致，按名取最后一条即得本轮产物
        （#32 引入裁决 agent 后重写本节点）。
        """
        by_name: dict[str, CharacterProfile] = {}
        for profile in state.get("character_profiles", []):
            by_name[profile.name] = profile
        return {"merged_profiles": list(by_name.values())}

    # ===== 剧本书写（骨架：Stage1Generator 承担；#33 退役）=====

    async def write_script(self, state: WorkflowState) -> dict[str, Any]:
        round_no = int(state.get("write_retries", 0)) + 1
        await self._report("write_script", f"书写第 {round_no} 轮开始")
        analysis = state["analysis"]
        extra_context: list[str] = []
        dossier = state.get("dossier")
        if dossier is not None:
            extra_context.append("【素材集结论】\n" + dossier.model_dump_json())
        division = state.get("division")
        if division is not None:
            extra_context.append("【事件划分草稿（必须遵守其场景/节拍结构）】\n"
                                 + division.model_dump_json())
        merged = state.get("merged_profiles") or []
        if merged:
            extra_context.append(
                "【人物设定（人物表以此为准）】\n"
                + json.dumps(
                    [p.model_dump(mode="json", exclude={"schema_version"}) for p in merged],
                    ensure_ascii=False,
                )
            )
        audit_feedback = state.get("audit_feedback")
        if audit_feedback:
            extra_context.append(f"【doubter 总审打回意见（必须逐条修正）】\n{audit_feedback}")
        outcome = await Stage1Generator(self._llm, model=self._model_name).generate(
            analysis,
            web_evidence=state.get("web_evidence") or [],
            session_id=state.get("session_id", ""),
            extra_context=extra_context,
            purpose=UsagePurpose.SCRIPT_WRITING,
            on_step=lambda text: self._report("write_script", text),
        )
        return {
            "package": outcome.script_package,
            "write_telemetry": {
                "model": outcome.telemetry.model,
                "prompt_version": outcome.telemetry.prompt_version,
                "schema_version": outcome.telemetry.schema_version,
                "latency_ms": outcome.telemetry.latency_ms,
                "token_count": outcome.telemetry.token_count,
                "retries": outcome.telemetry.retries,
            },
            "audit_feedback": None,
        }

    # ===== doubter 总审 =====

    async def final_audit(self, state: WorkflowState) -> dict[str, Any]:
        package = state.get("package")
        if package is None:
            raise new(codes.CNT_GENERATION_FAILED, extra={"reason": "package missing"})
        prompt = doubter.build_user_message(
            node_name="write_script",
            artifact_schema_hint="ScriptPackage{title, characters, scenes+beats, teaching_focus,"
            " playable_roles, stage2_ending_beat_id}",
            artifact_json=package.model_dump_json(),
            source_digest=self._source_digest(state),
        )
        raw = await self._chat(prompt, state, UsagePurpose.DOUBTER)
        try:
            verdict = _parse_verdict(raw)
        except ValueError as exc:
            logger.warning("[script-gen][final_audit] audit_verdict_parse_failed reason=%s", exc)
            verdict = VerdictResult("pass", [])
        retries = state.get("write_retries", 0) + (
            1 if verdict.verdict == "reject" else 0
        )
        return {
            "audit_verdict": verdict.verdict,
            "audit_issues": verdict.issues,
            "write_retries": retries,
            "audit_feedback": (
                "；".join(verdict.issues) if verdict.verdict == "reject" else None
            ),
        }

    def route_after_audit(self, state: WorkflowState) -> str:
        verdict = state.get("audit_verdict", "pass")
        if verdict == "pass":
            return "END"
        if state.get("write_retries", 0) <= MAX_WRITE_RETRIES:
            return "write_script"
        return "fail"

    # ===== 终止 =====

    async def fail(self, state: WorkflowState) -> dict[str, Any]:
        """打回耗尽的显式失败终点：异常上抛，runner 标记 attempt 失败。"""
        issues = state.get("doubter_issues") or state.get("audit_issues") or []
        reason = "；".join(issues) or "doubter 打回次数耗尽"
        raise new(codes.CNT_GENERATION_FAILED, extra={"reason": reason})


__all__ = ["WorkflowNodes", "MAX_DOUBTER_ROUNDS", "MAX_WRITE_RETRIES"]
