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

from langgraph.types import Send, interrupt
from pydantic import ValidationError

from app.contracts.content import TextAnalysis
from app.contracts.enums import UsagePurpose
from app.contracts.review import GateEdits
from app.contracts.script import CharacterProfile
from app.contracts.script_library import GenerationResumeRequest
from app.domain.generation.json_text import extract_json
from app.domain.generation.stage1 import Stage1Generator
from app.domain.generation.workflow.state import WorkflowState, state_web_evidence
from app.domain.generation.workflow.types import (
    EventDivisionDraft,
    MaterialDossier,
)
from app.domain.llm import LLMService
from app.domain.prompts import character_design, collect_materials, divide_events, doubter
from app.infrastructure.errx import codes, new

logger = logging.getLogger("wenjing.generation.workflow")

MAX_DOUBTER_ROUNDS = 2   # doubter 打回上限（沿用 stage1 MAX_RETRIES 心智）
MAX_WRITE_RETRIES = 2    # final_audit 打回剧本书写的上限
MAX_MAIN_CHARACTERS = 4  # 复现层主要人物数（骨架上限；#32 深化筛选）

# 节点内子进度回调：(workflow 节点键, detail 文本)；由 runner 注入，转发给进度 sink
ProgressHook = Callable[[str, str], Awaitable[None]]

# 教师闸门节点名（#34）：materials=素材收集后；pre_write=人物+场景划分后；
# final=总审通过后（终审：通过落库 / 打回重写，可编辑剧本字段）。
MATERIALS_GATE_NODE = "materials_gate"
PRE_WRITE_GATE_NODE = "pre_write_gate"
FINAL_GATE_NODE = "final_gate"


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
        teacher_gates: bool = False,
    ) -> None:
        self._llm = llm
        self._model_name = model_name
        self._teacher_gates = teacher_gates
        self._progress_hook: ProgressHook | None = None

    @property
    def gate_enabled(self) -> bool:
        """是否启用教师闸门（三道闸门的图拓扑都按此装配）。"""
        return self._teacher_gates

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

    async def _chat_parsed(
        self,
        state: WorkflowState,
        prompt: str,
        purpose: UsagePurpose,
        *,
        parse: Callable[[str], Any],
        target: str,
    ) -> Any:
        """结构化输出调用：解析失败带纠正提示重试一次。

        真实 LLM 偶发把 JSON 写坏（顶层提前闭合 / 兄弟片段拼接），一次
        重试能兜住绝大多数；两次仍失败才判 LLM_OUTPUT_PARSE_FAILED。
        """
        raw = await self._chat(prompt, state, purpose)
        try:
            return parse(raw)
        except Exception as first:
            reason = str(first).replace("\n", " ")[:200]
            raw = await self._chat(
                prompt
                + "\n\n【重试：上次输出解析失败】"
                + f"原因：{reason}。"
                + "请重新输出：只输出一个完整合法的 JSON 对象，"
                + "顶层花括号只有一对且在结尾闭合，JSON 之外不要有任何文字。",
                state,
                purpose,
            )
            try:
                return parse(raw)
            except Exception as exc:
                raise new(
                    codes.LLM_OUTPUT_PARSE_FAILED,
                    extra={"target": target, "reason": str(exc).replace("\n", " ")[:300]},
                ) from exc

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
        logger.info(
            "[script-gen][collect_materials] parsing materials (evidence=%d)...",
            len(state_web_evidence(state)),
        )
        prompt = collect_materials.build_user_message(
            analysis,
            state_web_evidence(state),
            feedback=state.get("doubter_feedback"),
        )
        dossier = await self._chat_parsed(
            state,
            prompt,
            UsagePurpose.COLLECT_MATERIALS,
            parse=lambda raw: MaterialDossier.model_validate_json(extract_json(raw)),
            target="MaterialDossier",
        )
        evidence = state_web_evidence(state)
        logger.info(
            "[script-gen][collect_materials] 素材收集完成 evidence=%d 人物笔记=%d 教学要点=%d",
            len(evidence),
            len(dossier.character_notes),
            len(dossier.teaching_analysis),
        )
        return {"dossier": dossier, "doubter_feedback": None}

    async def verify_materials(self, state: WorkflowState) -> dict[str, Any]:
        """doubter 质询素材集（骨架复用 doubter.v1；#30 框架化到全节点）。"""
        dossier = state.get("dossier")
        if dossier is None:  # 防御：打回回路丢失产物时直接失败
            raise new(codes.CNT_GENERATION_FAILED, extra={"reason": "dossier missing"})
        logger.info("[script-gen][verify_materials] doubter checking materials...")
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
            return MATERIALS_GATE_NODE if self.gate_enabled else "divide_events"
        if state.get("doubter_round", 0) <= MAX_DOUBTER_ROUNDS:
            return "collect_materials"
        return "fail"

    # ===== 教师闸门（#34：素材 / 人物+场景 / 终审三道闸）=====

    @staticmethod
    def _parse_resume(resume: Any) -> tuple[list[str], GateEdits, str]:
        """解析闸门恢复载荷（GenerationResumeRequest；旧列表载荷按指令处理）。"""
        if isinstance(resume, list):
            # 兼容旧调用方（早期 resume 只传 directives 列表）
            return [str(d) for d in resume if str(d).strip()], GateEdits(), "approve"
        if not isinstance(resume, dict):
            raise new(
                codes.CNT_GENERATION_FAILED,
                extra={"reason": "invalid gate resume payload"},
            )
        try:
            req = GenerationResumeRequest.model_validate(resume)
        except ValidationError as exc:
            # 教师恢复载荷非法：客户端输入错误，非 LLM 输出解析失败
            raise new(
                codes.CNT_GENERATION_FAILED,
                extra={
                    "reason": "invalid gate resume payload",
                    "detail": str(exc).replace("\n", " ")[:300],
                },
            ) from exc
        return req.directives, req.edits, req.action

    @staticmethod
    def _merge_directives(state: WorkflowState, incoming: list[str]) -> list[str]:
        merged = list(state.get("directives") or [])
        merged += [str(d) for d in incoming if str(d).strip()]
        return merged

    async def materials_gate(self, state: WorkflowState) -> dict[str, Any]:
        """素材闸门：暂停等教师审阅/编辑 dossier，恢复时应用编辑并并入指令。

        - 仅在 gate_enabled=True 时被装配进图（teacher_gates 控制拓扑）。
        - 首次执行在此 `interrupt()` 暂停；教师恢复时 LangGraph 以
          `Command(resume=payload)` 重放本节点，interrupt 返回恢复载荷。
        - 编辑语义（#34 裁决）：教师改后的 dossier 直接覆盖 state 通道，
          下游划分/书写以编辑稿为准，不重新考证；指令原样透传下游。
        """
        payload: dict[str, Any] = {
            "gate": "materials",
            "dossier": (
                state["dossier"].model_dump(mode="json")
                if state.get("dossier") is not None
                else None
            ),
            "evidence": list(state.get("web_evidence") or []),
        }
        resume = interrupt(payload)
        directives, edits, _ = self._parse_resume(resume)
        logger.info(
            "[script-gen][materials_gate] 教师恢复 directives=%d edits=%s",
            len(directives),
            sorted(edits.model_dump(exclude_none=True)),
        )
        out: dict[str, Any] = {"directives": self._merge_directives(state, directives)}
        if edits.dossier is not None:
            out["dossier"] = edits.dossier
            logger.info(
                "[script-gen][materials_gate] dossier edited by teacher "
                "(background=%d chars, notes=%d)",
                len(edits.dossier.background),
                len(edits.dossier.character_notes),
            )
        return out

    async def pre_write_gate(self, state: WorkflowState) -> dict[str, Any]:
        """中段闸门（#34）：人物+场景划分完成后暂停，教师审定/编辑后进入书写。

        展示事件划分草稿（场景名/参与人物/节拍）与人物设定；教师可编辑
        场景名、人物形象等，编辑稿直接覆盖对应通道传给剧本书写。
        """
        division = state.get("division")
        profiles = state.get("merged_profiles") or []
        payload: dict[str, Any] = {
            "gate": "pre_write",
            "division": (
                division.model_dump(mode="json") if division is not None else None
            ),
            "profiles": [p.model_dump(mode="json") for p in profiles],
        }
        resume = interrupt(payload)
        directives, edits, _ = self._parse_resume(resume)
        logger.info(
            "[script-gen][pre_write_gate] 教师恢复 directives=%d", len(directives)
        )
        out: dict[str, Any] = {"directives": self._merge_directives(state, directives)}
        if edits.division is not None:
            out["division"] = edits.division
            logger.info(
                "[script-gen][pre_write_gate] division edited by teacher (scenes=%d)",
                len(edits.division.scenes),
            )
        if edits.profiles is not None:
            out["merged_profiles"] = edits.profiles
            logger.info(
                "[script-gen][pre_write_gate] profiles edited by teacher (%d)",
                len(edits.profiles),
            )
        return out

    async def final_gate(self, state: WorkflowState) -> dict[str, Any]:
        """终审闸门（#34）：总审通过后暂停，教师通过落库或打回重写。

        - approve：编辑后的剧本包直接生效，流程结束落库。
        - reject：把指导作为打回意见送回 write_script 重写一轮；
          教师也可同时直接编辑剧本字段（编辑稿作为重写基线）。
        """
        package = state.get("package")
        payload: dict[str, Any] = {
            "gate": "final",
            "package": (
                package.model_dump(mode="json") if package is not None else None
            ),
        }
        resume = interrupt(payload)
        directives, edits, action = self._parse_resume(resume)
        logger.info(
            "[script-gen][final_gate] 教师恢复 action=%s directives=%d", action, len(directives)
        )
        out: dict[str, Any] = {
            "gate_action": action,
            "directives": self._merge_directives(state, directives),
        }
        if edits.package is not None:
            out["package"] = edits.package
            logger.info(
                "[script-gen][final_gate] package edited by teacher (scenes=%d)",
                len(edits.package.scenes),
            )
        if action == "reject":
            feedback_parts: list[str] = [
                str(d) for d in directives if str(d).strip()
            ]
            if edits.package is not None:
                # 编辑语义（#34 裁决）：打回重写时教师编辑稿是重写基线，
                # 把编辑稿随打回意见送入书写上下文，避免编辑被静默丢弃
                feedback_parts.append(
                    "【教师终审编辑稿（重写必须保留这些修订）】\n"
                    + edits.package.model_dump_json()
                )
            out["audit_feedback"] = "；".join(feedback_parts) or "教师打回，请根据指导重写"
            # 计入书写轮次（与 doubter 打回同一上限心智）；DoubterEvent 轮次
            # 投影侧有 min 收口，防超出契约上限。
            out["write_retries"] = int(state.get("write_retries", 0)) + 1
        return out

    def route_after_final_gate(self, state: WorkflowState) -> str:
        # 终审打回是教师主动行为，不受 doubter 的 MAX_WRITE_RETRIES 上限
        # 约束（教学判断优先，#34）；教师可反复打回直到满意。
        return "write_script" if state.get("gate_action") == "reject" else "END"

    # ===== 事件/情景划分 =====

    async def divide_events(self, state: WorkflowState) -> dict[str, Any]:
        analysis = state["analysis"]
        dossier = state.get("dossier")
        dossier_json = dossier.model_dump_json() if dossier is not None else "{}"
        directives = state.get("directives") or []
        logger.info(
            "[script-gen][divide_events] parsing scenes (directives=%d)...",
            len(directives),
        )
        prompt = divide_events.build_user_message(
            analysis,
            dossier_json,
            directives=directives,
        )
        division = await self._chat_parsed(
            state,
            prompt,
            UsagePurpose.DIVIDE_EVENTS,
            parse=lambda raw: EventDivisionDraft.model_validate_json(extract_json(raw)),
            target="EventDivisionDraft",
        )
        self._validate_division(analysis, division)
        scenes = len(division.scenes)
        beats = sum(len(s.beats) for s in division.scenes)
        key_beats = sum(
            1 for s in division.scenes for b in s.beats if b.is_key_event
        )
        logger.info(
            "[script-gen][divide_events] 划分完毕 scenes=%d beats=%d key_beats=%d",
            scenes,
            beats,
            key_beats,
        )
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
        logger.info("[script-gen][design_one_character] building character: %s", payload["name"])
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
        logger.info(
            "[script-gen][merge_characters] merging %d character profiles...",
            len(state.get("character_profiles", [])),
        )
        by_name: dict[str, CharacterProfile] = {}
        for profile in state.get("character_profiles", []):
            by_name[profile.name] = profile
        return {"merged_profiles": list(by_name.values())}

    # ===== 剧本书写（骨架：Stage1Generator 承担；#33 退役）=====

    async def write_script(self, state: WorkflowState) -> dict[str, Any]:
        round_no = int(state.get("write_retries", 0)) + 1
        await self._report("write_script", f"书写第 {round_no} 轮开始")
        division = state.get("division")
        logger.info(
            "[script-gen][write_script] writing script round=%d (scenes=%d, characters=%d)...",
            round_no,
            len(division.scenes) if division is not None else 0,
            len(state.get("merged_profiles") or []),
        )
        analysis = state["analysis"]
        extra_context: list[str] = []
        dossier = state.get("dossier")
        if dossier is not None:
            extra_context.append("【素材集结论】\n" + dossier.model_dump_json())
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
        directives = state.get("directives") or []
        if directives:
            # #34 指导语义：教师指令原样作为额外约束传给下游生成 agent
            extra_context.append(
                "【教师指导指令（必须遵守）】\n" + "\n".join(f"- {d}" for d in directives)
            )
        outcome = await Stage1Generator(self._llm, model=self._model_name).generate(
            analysis,
            web_evidence=state_web_evidence(state),
            session_id=state.get("session_id", ""),
            extra_context=extra_context,
            purpose=UsagePurpose.SCRIPT_WRITING,
            on_step=lambda text: self._report("write_script", text),
        )
        package = outcome.script_package
        logger.info(
            "[script-gen][write_script] 剧本完成 scenes=%d beats=%d characters=%d",
            len(package.scenes),
            sum(len(s.beats) for s in package.scenes),
            len(package.characters),
        )
        return {
            "package": package,
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
        logger.info("[script-gen][final_audit] auditing script...")
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
            return FINAL_GATE_NODE if self.gate_enabled else "END"
        if state.get("write_retries", 0) <= MAX_WRITE_RETRIES:
            return "write_script"
        return "fail"

    # ===== 终止 =====

    async def fail(self, state: WorkflowState) -> dict[str, Any]:
        """打回耗尽的显式失败终点：异常上抛，runner 标记 attempt 失败。"""
        issues = state.get("doubter_issues") or state.get("audit_issues") or []
        reason = "；".join(issues) or "doubter 打回次数耗尽"
        raise new(codes.CNT_GENERATION_FAILED, extra={"reason": reason})


__all__ = [
    "MATERIALS_GATE_NODE",
    "PRE_WRITE_GATE_NODE",
    "FINAL_GATE_NODE",
    "WorkflowNodes",
    "MAX_DOUBTER_ROUNDS",
    "MAX_WRITE_RETRIES",
]
