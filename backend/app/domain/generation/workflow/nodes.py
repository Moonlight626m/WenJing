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
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from langgraph.types import Send, interrupt
from pydantic import ValidationError

from app.contracts.content import TextAnalysis
from app.contracts.enums import UsagePurpose
from app.contracts.generation import DoubterIssue, DoubterVerdict
from app.contracts.review import AssetOp, GateEdits
from app.contracts.script import AssetCredit, AssetRef, CharacterProfile, ScriptPackage
from app.contracts.script_library import GenerationResumeRequest
from app.domain.game.media import (
    AssetKind,
    AssetStatus,
    SceneDesigner,
    scene_visual_description,
    to_asset_ref,
    to_contract_credit,
)
from app.domain.generation.json_text import extract_json
from app.domain.generation.stage1 import Stage1Generator
from app.domain.generation.workflow.state import (
    WorkflowState,
    state_dossier,
    state_web_evidence,
)
from app.domain.generation.workflow.types import (
    EventDivisionDraft,
    MaterialDossier,
)
from app.domain.llm import LLMService
from app.domain.prompts import character_design, collect_materials, divide_events, doubter
from app.domain.prompts.bundle import PromptBundle
from app.domain.prompts.defaults import STAGE as SCRIPT_GEN_STAGE
from app.domain.prompts.manager import PromptManager
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


def _format_issue(issue: DoubterIssue) -> str:
    """DoubterIssue → 教师可见的一行文本（进度/闸门投影用）。"""
    parts = [f"[{issue.severity}] {issue.category} @{issue.field}"]
    if issue.quote:
        parts.append(f"「{issue.quote}」")
    if issue.evidence:
        parts.append(f"依据：{issue.evidence}")
    if issue.suggestion:
        parts.append(f"建议：{issue.suggestion}")
    return "".join(parts)


def _feedback_text(issues: list[DoubterIssue]) -> str:
    """结构化问题清单 → 打回意见文本（must-fix 置顶，逐条可执行）。"""
    ordered = sorted(
        issues, key=lambda i: 0 if i.severity == "must_fix" else 1
    )
    lines = [f"- {_format_issue(i)}" for i in ordered]
    return "以下问题必须逐条修正：\n" + "\n".join(lines)


def _asset_ref_of(asset_id: uuid.UUID, kind: AssetKind) -> AssetRef:
    """旧图引用重建（#49 重生成失败保图用）：status 按 READY 语义回填。

    槽位上既然挂着这张图（#48 只回填 READY），重建为 ready 与其持久化状态
    一致；真正的状态以 `GET /api/assets/{id}/url` 的鉴权检查为准。
    """
    return AssetRef(asset_id=asset_id, kind=kind.value, status="ready")


def _apply_assets(
    package: ScriptPackage,
    scenes: dict[int, AssetRef],
    profiles: dict[str, AssetRef],
    scene_credits: dict[int, AssetCredit | None] | None = None,
    profile_credits: dict[str, AssetCredit | None] | None = None,
) -> ScriptPackage:
    """把 AssetRef/AssetCredit 写回剧本包（不可变契约：model_copy 重建受影响条目）。

    打回重写后 write_script 产出全新场景集，此函数只在 design_assets 的
    返回 delta 上生效，不存在「旧轮 AssetRef 粘到新场景」的通道污染。
    credit 只对检索件非 None（#51：教师端完整展示署名；学生端过滤在展示侧）。
    """
    if not scenes and not profiles:
        return package
    scene_credits = scene_credits or {}
    profile_credits = profile_credits or {}
    new_scenes = [
        (
            scene.model_copy(
                update={
                    "background_asset": scenes[scene.scene_id],
                    "background_credit": scene_credits.get(scene.scene_id),
                }
            )
            if scene.scene_id in scenes
            else scene
        )
        for scene in package.scenes
    ]
    new_characters = [
        (
            c.model_copy(
                update={
                    "avatar_asset": profiles[c.name],
                    "avatar_credit": profile_credits.get(c.name),
                }
            )
            if c.name in profiles
            else c
        )
        for c in package.characters
    ]
    return package.model_copy(
        update={"scenes": new_scenes, "characters": new_characters}
    )


def _parse_verdict(raw: str) -> DoubterVerdict:
    data = json.loads(extract_json(raw))
    verdict = DoubterVerdict.model_validate(data)
    must_fix = any(i.severity == "must_fix" for i in verdict.issues)
    if verdict.verdict == "reject" and not must_fix:
        raise ValueError("reject verdict requires at least one must_fix issue")
    if verdict.verdict == "pass" and must_fix:
        raise ValueError("must_fix issue present but verdict is pass")
    return verdict


class WorkflowNodes:
    """节点集合：以 LLM 服务为依赖闭包，供 build_workflow 装配。"""

    def __init__(
        self,
        llm: LLMService,
        *,
        model_name: str = "",
        teacher_gates: bool = False,
        prompts: PromptManager | None = None,
        scene_designer: SceneDesigner | None = None,
    ) -> None:
        self._llm = llm
        self._model_name = model_name
        self._teacher_gates = teacher_gates
        self._prompts = prompts or PromptManager()
        # 场景资产编排（#48）：组合根注入；None 时 design_assets 节点直接跳过
        # （测试 / 无媒体配置环境不出图）。SceneDesigner 与本模块同层（domain），
        # 运行时 import 无环。script_library 侧还接受零参 callable 延迟求值，
        # 到这里已解包为实例或 None。
        self._scene_designer = scene_designer
        self._progress_hook: ProgressHook | None = None

    @property
    def gate_enabled(self) -> bool:
        """是否启用教师闸门（三道闸门的图拓扑都按此装配）。"""
        return self._teacher_gates

    def set_progress_hook(self, hook: ProgressHook | None) -> None:
        """注入节点内子进度回调（runner 在建图后调用）。"""
        self._progress_hook = hook

    # ===== 工具 =====

    async def _bundle(self, node_module) -> PromptBundle:  # noqa: ANN001 - 模块常量载体
        """取节点 prompt 段落集合（DB 覆盖优先，缺省回退 defaults）。"""
        return await self._prompts.bundle(
            SCRIPT_GEN_STAGE, node_module.NODE, node_module.VERSION
        )

    async def _report(self, node: str, detail: str) -> None:
        """向进度 sink 推送节点内子进度（无 hook 时静默）。"""
        if self._progress_hook is not None:
            await self._progress_hook(node, detail)

    async def _chat(self, prompt: str, session_id: str, purpose: UsagePurpose) -> str:
        return await self._llm.chat(
            [{"role": "user", "content": prompt}],
            session_id=session_id,
            purpose=purpose,
        )

    async def _chat_parsed(
        self,
        prompt: str,
        session_id: str,
        purpose: UsagePurpose,
        *,
        parse: Callable[[str], Any],
        target: str,
    ) -> Any:
        """结构化输出调用：解析失败带纠正提示重试一次。

        真实 LLM 偶发把 JSON 写坏（顶层提前闭合 / 兄弟片段拼接 / 字符串内
        未转义的英文双引号），一次重试能兜住绝大多数；两次仍失败才判
        LLM_OUTPUT_PARSE_FAILED。
        """
        raw = await self._chat(prompt, session_id, purpose)
        try:
            return parse(raw)
        except Exception as first:
            reason = str(first).replace("\n", " ")[:200]
            raw = await self._chat(
                prompt
                + "\n\n【重试：上次输出解析失败】"
                + f"原因：{reason}。"
                + "请重新输出：只输出一个完整合法的 JSON 对象，"
                + "顶层花括号只有一对且在结尾闭合，JSON 之外不要有任何文字；"
                + "字符串内部如需引用，一律改用中文引号「」或''，"
                + "禁止出现未转义的英文双引号。",
                session_id,
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
        dossier = state_dossier(state)
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
            bundle=await self._bundle(collect_materials),
        )
        dossier = await self._chat_parsed(
            prompt,
            state.get("session_id", ""),
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
        return {
            # 通道存 JSON-safe dict：dossier 带 web claims 时 checkpointer 的
            # msgpack 序列化不了 model_dump() 里的 HttpUrl/datetime 对象（#68）。
            "dossier": dossier.model_dump(mode="json"),
            "doubter_feedback": None,
        }

    async def verify_materials(self, state: WorkflowState) -> dict[str, Any]:
        """doubter 质询素材集（骨架复用 doubter.v1；#30 框架化到全节点）。"""
        dossier = state_dossier(state)
        if dossier is None:  # 防御：打回回路丢失产物时直接失败
            raise new(codes.CNT_GENERATION_FAILED, extra={"reason": "dossier missing"})
        logger.info("[script-gen][verify_materials] doubter checking materials...")
        prompt = doubter.build_user_message(
            node_name="collect_materials",
            artifact_schema_hint=(
                "MaterialDossier{background, era_setting, character_notes:[{name,note}],"
                " plot_summary, teaching_analysis, claims, conflicts}"
            ),
            artifact_json=dossier.model_dump_json(),
            source_digest=self._analysis_digest(state["analysis"]),
            bundle=await self._bundle(doubter),
        )
        raw = await self._chat(prompt, state.get("session_id", ""), UsagePurpose.DOUBTER)
        try:
            verdict = _parse_verdict(raw)
        except ValueError as exc:
            logger.warning(
                "[script-gen][verify_materials] doubter_verdict_parse_failed reason=%s", exc
            )
            verdict = DoubterVerdict(verdict="pass", issues=[])  # doubter 异常不阻塞主流程
        round_no = state.get("doubter_round", 0) + 1
        return {
            "doubter_verdict": verdict.verdict,
            "doubter_issues": [_format_issue(i) for i in verdict.issues],
            "doubter_round": round_no,
            "doubter_feedback": (
                _feedback_text(verdict.issues) if verdict.verdict == "reject" else None
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
        dossier_snapshot = state_dossier(state)
        payload: dict[str, Any] = {
            "gate": "materials",
            "dossier": (
                dossier_snapshot.model_dump(mode="json")
                if dossier_snapshot is not None
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
            # 通道存 JSON-safe dict（同 collect_materials 返回值；#68）
            out["dossier"] = edits.dossier.model_dump(mode="json")
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

        - approve：编辑后的剧本包直接生效，流程结束落库；教师配图操作
          （#49 asset_ops）在此一并生效——终审是唯一能同时看到剧本与配图
          的闸门（#48 选项 A 把配图放在总审之后）。
        - reject：把指导作为打回意见送回 write_script 重写一轮；
          教师也可同时直接编辑剧本字段（编辑稿作为重写基线）。reject 时
          **忽略 asset_ops**：重写产出全新场景集，旧槽位上的操作必然失效。
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
        if edits.asset_ops:
            if action == "reject":
                logger.info(
                    "[script-gen][final_gate] asset_ops=%d ignored on reject (rewrite "
                    "produces a fresh package)",
                    len(edits.asset_ops),
                )
            else:
                target = out.get("package") or state.get("package")
                org_raw = state.get("org_id") or ""
                try:
                    org_id = uuid.UUID(org_raw)
                except ValueError:
                    org_id = None
                    logger.warning(
                        "[script-gen][final_gate] asset_ops skipped (bad org_id %r)",
                        org_raw,
                    )
                if target is not None and org_id is not None:
                    try:
                        user_id = uuid.UUID(state.get("user_id") or "")
                    except ValueError:
                        user_id = None
                    out["package"] = await self._apply_asset_ops(
                        target,
                        edits.asset_ops,
                        org_id=org_id,
                        user_id=user_id,
                        script_id=int(state.get("script_id") or 0),
                    )
                    logger.info(
                        "[script-gen][final_gate] asset_ops applied (%d)",
                        len(edits.asset_ops),
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

    # ===== 场景/角色配图（#48）=====

    async def design_assets(self, state: WorkflowState) -> dict[str, Any]:
        """生成期预生成（ADR-0005 §7 / 设计文档 M2-6a）：为总审通过的剧本包配图。

        位置在 final_audit **之后**：先审计故事事实、再为定稿配图，doubter 打回
        的轮次不会白付配图钱；教师终审闸（若启用）随后的审阅载荷自然带上配图
        （#49 的资产通道挂在 final gate）。

        - **幂等**：SceneDesigner 按 (org, script, scene/kind, 描述, 风格, provider)
          去重，resume/重跑命中 READY 缓存不重复付费。幂等性覆盖**描述漂移**：
          同一 subject 的描述与既有 READY 资产一致才复用缓存；打回重写改写了
          节拍文本时键随之变化、按新描述重新生成（旧资产仍留存，不删）。
        - **降级**：单个主体（场景/人物）的任何失败——编排返回 FAILED **或**
          DB 等非预期异常（`design_scene` 契约：仅媒体类失败内部降级）——只让
          该主体无图（AssetRef 不填），绝不拖垮已通过总审的剧本。org/user 缺失
          同样整体跳过（计量与配额都要求归属，没有归属就不该花钱）。
        """
        designer = self._scene_designer
        package = state.get("package")
        if designer is None:
            logger.info("[script-gen][design_assets] no designer wired, skip")
            return {"asset_summary": {"skipped": "no_designer"}}
        if package is None:  # 防御：打回回路丢失产物时由 fail 节点语义兜底
            raise new(codes.CNT_GENERATION_FAILED, extra={"reason": "package missing"})
        org_raw = state.get("org_id") or ""
        user_raw = state.get("user_id") or ""
        try:
            org_id = uuid.UUID(org_raw)
        except ValueError:
            logger.warning(
                "[script-gen][design_assets] no org_id in state, skip (org=%r)", org_raw
            )
            return {"asset_summary": {"skipped": "no_org"}}
        try:
            user_id = uuid.UUID(user_raw) if user_raw else None
        except ValueError:
            logger.warning(
                "[script-gen][design_assets] bad user_id in state, meter without user (%r)",
                user_raw,
            )
            user_id = None
        script_id = int(state.get("script_id") or 0)

        updated_scenes: dict[int, AssetRef] = {}
        updated_profiles: dict[str, AssetRef] = {}
        scene_credits: dict[int, AssetCredit | None] = {}
        profile_credits: dict[str, AssetCredit | None] = {}
        total = len(package.scenes) + len(package.characters)
        done = 0
        for scene in package.scenes:
            done += 1
            await self._report(
                "design_assets", f"配图 {done}/{total}：场景「{scene.title}」"
            )
            picked = await self._design_one(
                designer,
                subject_key=f"scene:{scene.scene_id}",
                scene_key=f"script:{script_id}:scene:{scene.scene_id}",
                description=scene_visual_description(scene),
                kind=AssetKind.BACKGROUND,
                org_id=org_id,
                script_id=script_id,
                user_id=user_id,
                label=f"场景「{scene.title}」",
            )
            if picked is not None:
                # 降级：失败主体不进剧本包，该场景以纯文本游玩
                ref, credit = picked
                updated_scenes[scene.scene_id] = ref
                scene_credits[scene.scene_id] = credit
        for profile in package.characters:
            done += 1
            await self._report("design_assets", f"配图 {done}/{total}：人物「{profile.name}」")
            picked = await self._design_one(
                designer,
                subject_key=f"character:{profile.name}",
                scene_key=f"script:{script_id}:character:{profile.name}",
                description=profile.public_background,
                kind=AssetKind.AVATAR,
                org_id=org_id,
                script_id=script_id,
                user_id=user_id,
                label=f"人物「{profile.name}」",
            )
            if picked is not None:
                ref, credit = picked
                updated_profiles[profile.name] = ref
                profile_credits[profile.name] = credit

        out: dict[str, Any] = {
            "package": _apply_assets(
                package, updated_scenes, updated_profiles, scene_credits, profile_credits
            ),
            "asset_summary": {
                "scenes_ready": len(updated_scenes),
                "scenes_total": len(package.scenes),
                "avatars_ready": len(updated_profiles),
                "avatars_total": len(package.characters),
            },
        }
        logger.info(
            "[script-gen][design_assets] 配图完成 scenes=%d/%d avatars=%d/%d",
            len(updated_scenes),
            len(package.scenes),
            len(updated_profiles),
            len(package.characters),
        )
        return out

    @staticmethod
    async def _design_one(
        designer: SceneDesigner,
        *,
        subject_key: str,
        scene_key: str,
        description: str,
        kind: AssetKind,
        org_id: uuid.UUID,
        script_id: int,
        user_id: uuid.UUID | None,
        label: str,
    ) -> tuple[AssetRef, AssetCredit | None] | None:
        """单个主体的配图：READY → (AssetRef, 契约署名)；FAILED/异常 → None。

        场景循环与人物循环的差异只在键与回填目标，此处收拢「调用 → 判状态 →
        异常兜底」这一共享形状；失败主体记 warning 后返回 None，剧本照常可用。
        署名只对检索件非 None（#51，生成/上传件无许可语义）。
        """
        try:
            record = await designer.design_scene(
                org_id=org_id,
                subject_key=subject_key,
                scene_key=scene_key,
                description=description,
                kind=kind,
                script_id=script_id,
                user_id=user_id,
            )
        except Exception as exc:  # noqa: BLE001 - 单主体失败不拖垮整单剧本
            logger.warning(
                "scene_asset_design_error subject=%s reason=%s",
                subject_key,
                str(exc).replace("\n", " ")[:200],
            )
            return None
        if record.status is AssetStatus.READY:
            return to_asset_ref(record), to_contract_credit(record)
        logger.warning(
            "[script-gen][design_assets] asset failed %s subject=%s status=%s",
            label,
            subject_key,
            record.status.value,
        )
        return None

    # ===== 教师配图操作（#49）：final_gate approve 路径生效 =====

    async def _apply_asset_ops(
        self,
        package: ScriptPackage,
        ops: list[AssetOp],
        *,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None,
        script_id: int,
    ) -> ScriptPackage:
        """对终审剧本包应用教师配图操作（GateEdits.asset_ops）。

        - 语义见 `AssetOp` 契约；同一 subject 多条时**最后一条胜出**；
        - 重生成/检索替换的描述与旧图 id 都取自**终审包的槽位本身**（场景
          节拍文本 / 人物 public_background、background_asset/avatar_asset），
          与 #48 首次配图同源——描述一致才命中 SceneDesigner 的既有语义
          （排除集保证换图）；
        - 单条操作失败（找不到槽位/上传件不可绑定/重生成 FAILED）只让该条
          不生效并记 warning，绝不拖垮已通过总审的剧本（与 #48 降级同构）；
        - remove 资产行留存（ADR-0005：删除/回收暂不立项），只是槽位清空。
        """
        last_by_subject: dict[tuple[str, str], AssetOp] = {}
        for op in ops:
            last_by_subject[(op.subject_key, op.kind)] = op

        scene_ops: dict[int, AssetRef | None] = {}
        profile_ops: dict[str, AssetRef | None] = {}
        scene_credit_ops: dict[int, AssetCredit | None] = {}
        profile_credit_ops: dict[str, AssetCredit | None] = {}
        scenes_by_id = {s.scene_id: s for s in package.scenes}
        profiles_by_name = {c.name: c for c in package.characters}
        for (subject_key, kind_raw), op in last_by_subject.items():
            kind = AssetKind(kind_raw)
            # kind↔槽位校验：本阶段只产出 background（场景）与 avatar（人物），
            # fullbody 通道未接线；错位操作（如对头像槽发 background）忽略，
            # 否则 fullbody 引用会被写进 avatar 槽、其失败回退也会串 kind。
            if subject_key.startswith("scene:"):
                if kind is not AssetKind.BACKGROUND:
                    logger.warning(
                        "asset_op kind=%s on scene subject ignored", kind.value
                    )
                    continue
                try:
                    scene = scenes_by_id[int(subject_key.split(":", 1)[1])]
                except (KeyError, ValueError):
                    logger.warning("asset_op unknown subject=%r ignored", subject_key)
                    continue
                ref, credit = await self._resolve_op(
                    op,
                    kind,
                    designer=self._scene_designer,
                    org_id=org_id,
                    user_id=user_id,
                    script_id=script_id,
                    description=scene_visual_description(scene),
                    current_asset_id=(
                        scene.background_asset.asset_id
                        if scene.background_asset
                        else None
                    ),
                    current_credit=scene.background_credit,
                )
                scene_ops[scene.scene_id] = ref
                scene_credit_ops[scene.scene_id] = credit
            elif subject_key.startswith("character:"):
                if kind is not AssetKind.AVATAR:
                    logger.warning(
                        "asset_op kind=%s on character subject ignored", kind.value
                    )
                    continue
                name = subject_key.split(":", 1)[1]
                profile = profiles_by_name.get(name)
                if profile is None:
                    logger.warning("asset_op unknown subject=%r ignored", subject_key)
                    continue
                ref, credit = await self._resolve_op(
                    op,
                    kind,
                    designer=self._scene_designer,
                    org_id=org_id,
                    user_id=user_id,
                    script_id=script_id,
                    description=profile.public_background,
                    current_asset_id=(
                        profile.avatar_asset.asset_id if profile.avatar_asset else None
                    ),
                    current_credit=profile.avatar_credit,
                )
                profile_ops[name] = ref
                profile_credit_ops[name] = credit
            else:
                logger.warning("asset_op unknown subject=%r ignored", subject_key)

        new_scenes = [
            (
                scene.model_copy(
                    update={
                        "background_asset": scene_ops[scene.scene_id],
                        "background_credit": scene_credit_ops[scene.scene_id],
                    }
                )
                if scene.scene_id in scene_ops
                else scene
            )
            for scene in package.scenes
        ]
        new_characters = [
            (
                c.model_copy(
                    update={
                        "avatar_asset": profile_ops[c.name],
                        "avatar_credit": profile_credit_ops[c.name],
                    }
                )
                if c.name in profile_ops
                else c
            )
            for c in package.characters
        ]
        return package.model_copy(
            update={"scenes": new_scenes, "characters": new_characters}
        )

    @staticmethod
    async def _resolve_op(
        op: AssetOp,
        kind: AssetKind,
        *,
        designer: SceneDesigner | None,
        org_id: uuid.UUID,
        user_id: uuid.UUID | None,
        script_id: int,
        description: str,
        current_asset_id: uuid.UUID | None,
        current_credit: AssetCredit | None,
    ) -> tuple[AssetRef | None, AssetCredit | None]:
        """单条操作 → 槽位新值 (ref, credit)；ref=None 的语义随 op 而定。

        - remove：None 即「清空」（教师明确意图，署名一并清）；
        - regenerate/search_replace 失败：返回旧图引用与旧署名保留原状——
          检索替换的契约是「失败不丢图」；槽位本来无图时失败返回 (None, None)。
        - bind_upload：上传件非检索来源，署名为 None（#51 展示语义）。
        """
        if op.op == "remove":
            return None, None
        if designer is None:
            logger.warning("asset_op %s without designer ignored", op.op)
            return None, None
        if op.op == "bind_upload":
            if op.asset_id is None:
                logger.warning("bind_upload without asset_id ignored")
                return None, None
            record = await designer.find_bindable_upload(
                asset_id=op.asset_id, org_id=org_id, kind=kind
            )
            if record is None:
                logger.warning(
                    "bind_upload not bindable asset=%s kind=%s",
                    op.asset_id,
                    kind.value,
                )
                return None, None
            return to_asset_ref(record), to_contract_credit(record)

        # regenerate / search_replace：排除旧图，按同键重新设计
        def keep_old() -> tuple[AssetRef | None, AssetCredit | None]:
            # 失败保留旧图与旧署名（None 会把槽位清空，那是 remove 的语义）
            return (
                (_asset_ref_of(current_asset_id, kind), current_credit)
                if current_asset_id
                else (None, None)
            )

        try:
            record = await designer.design_scene(
                org_id=org_id,
                subject_key=op.subject_key,
                scene_key=f"script:{script_id}:{op.subject_key}",
                description=description,
                kind=kind,
                script_id=script_id,
                user_id=user_id,
                exclude_asset_ids=(current_asset_id,) if current_asset_id else (),
                search_only=op.op == "search_replace",
            )
        except Exception as exc:  # noqa: BLE001 - 单条操作失败不拖垮剧本
            logger.warning(
                "asset_op %s error subject=%s reason=%s",
                op.op,
                op.subject_key,
                str(exc).replace("\n", " ")[:200],
            )
            return keep_old()
        if record.status is AssetStatus.READY:
            return to_asset_ref(record), to_contract_credit(record)
        logger.warning(
            "asset_op %s degraded subject=%s status=%s (slot keeps old image)",
            op.op,
            op.subject_key,
            record.status.value,
        )
        return keep_old()

    # ===== 事件/情景划分 =====

    async def divide_events(self, state: WorkflowState) -> dict[str, Any]:
        analysis = state["analysis"]
        dossier = state_dossier(state)
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
            bundle=await self._bundle(divide_events),
        )
        division = await self._chat_parsed(
            prompt,
            state.get("session_id", ""),
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
            ip = scene.interaction_point
            if ip is not None:
                ghost_orders = [o for o in ip.must_not_change if o not in known_orders]
                if ghost_orders:
                    raise new(
                        codes.LLM_OUTPUT_PARSE_FAILED,
                        extra={
                            "target": "EventDivisionDraft",
                            "reason": (
                                f"介入点 must_not_change 引用了不存在的关键事件 {ghost_orders}"
                            ),
                        },
                    )

    # ===== 人物设定（Send 并行）=====

    def design_characters(self, state: WorkflowState) -> list[Send]:
        """按原文戏份选出主要人物，Send fan-out 并行生成设定（#32 深化）。"""
        analysis = state["analysis"]
        dossier = state_dossier(state)
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
            bundle=await self._bundle(character_design),
        )

        def _parse(raw: str) -> CharacterProfile:
            data = json.loads(extract_json(raw))
            data["name"] = payload["name"]
            return CharacterProfile.model_validate(data)

        profile = await self._chat_parsed(
            prompt,
            payload.get("session_id", ""),
            UsagePurpose.CHARACTER_DESIGN,
            parse=_parse,
            target="CharacterProfile",
        )
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
        dossier = state_dossier(state)
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
        outcome = await Stage1Generator(
            self._llm,
            model=self._model_name,
            prompts=self._prompts,
        ).generate(
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
            bundle=await self._bundle(doubter),
        )
        raw = await self._chat(prompt, state.get("session_id", ""), UsagePurpose.DOUBTER)
        try:
            verdict = _parse_verdict(raw)
        except ValueError as exc:
            logger.warning("[script-gen][final_audit] audit_verdict_parse_failed reason=%s", exc)
            verdict = DoubterVerdict(verdict="pass", issues=[])
        retries = state.get("write_retries", 0) + (
            1 if verdict.verdict == "reject" else 0
        )
        return {
            "audit_verdict": verdict.verdict,
            "audit_issues": [_format_issue(i) for i in verdict.issues],
            "write_retries": retries,
            "audit_feedback": (
                _feedback_text(verdict.issues) if verdict.verdict == "reject" else None
            ),
        }

    def route_after_audit(self, state: WorkflowState) -> str:
        verdict = state.get("audit_verdict", "pass")
        if verdict == "pass":
            # #48：总审通过先配图；design_assets 再按拓扑接终审闸（gate on）或 END
            return "design_assets"
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
    "DoubterVerdict",
]
