"""剧本库应用服务（issue #19 / ADR-0002 §3；#28 workflow 骨架接入）。

- 教师：导入素材 → 建草稿 → 异步生成 → 发布（org/public）/下架 → 删除/重新生成。
- 生成两条路径（#28）：配置了 LLM key 时走 LangGraph workflow（多节点 +
  doubter，进度落 `script_generations`）；未配置时保留旧确定性合成路径
  （测试与 E2E 依赖，#33 退役）。进度统一经 GenerationProgress 契约读取。
- 单 worker 约束不变：workflow 在进程内 asyncio 任务执行；闸门/断点恢复
  依赖注入的 AsyncPostgresSaver checkpointer（#34 启用 interrupt）。
- 归属：素材与剧本独立归属 owner/org；仅 owner 可变更，已发布剧本对同 org
  （或跨 org 公开）只读可见。
"""

from __future__ import annotations

import asyncio
import logging
import uuid

from sqlalchemy import or_, select

from app.contracts.content import TextAnalysis
from app.contracts.enums import ScriptStatus, ScriptVisibility, UsagePurpose
from app.contracts.generation import (
    GenerationNode,
    GenerationNodeStatus,
    GenerationProgress,
    GenerationStatus,
    NodeProgress,
)
from app.contracts.material import MaterialInput
from app.domain.access import Actor, script_visible_to
from app.domain.content.pipeline import ContentPipeline
from app.domain.generation.stage1 import (
    PROMPT_VERSION,
    GenerationTelemetry,
    Stage1Generator,
    synthesize_script_package,
)
from app.domain.generation.workflow import WorkflowNodes, WorkflowRunner, initial_state
from app.infrastructure.errx import codes, new
from app.infrastructure.models.material import Material as MaterialRecord
from app.infrastructure.models.script import Script as ScriptRecord
from app.infrastructure.models.script_generation import ScriptGeneration as ScriptGenerationRecord
from app.infrastructure.rag.service import RagService

logger = logging.getLogger("wenjing.scripts.library")

# fire-and-forget 后台清理任务的强引用集（防 GC 中途回收，S7）
_background_tasks: set[asyncio.Task] = set()


def _telemetry_dict(telemetry: GenerationTelemetry) -> dict:
    """GenerationTelemetry → scripts.verification 落库形状。"""
    return {
        "model": telemetry.model,
        "prompt_version": telemetry.prompt_version,
        "schema_version": telemetry.schema_version,
        "latency_ms": telemetry.latency_ms,
        "token_count": telemetry.token_count,
        "retries": telemetry.retries,
        "used_web_evidence": telemetry.used_web_evidence,
    }


def _prompt_versions() -> dict[str, str]:
    """各 workflow 节点的 prompt 版本快照（S5：telemetry 可溯源）。"""
    from app.domain.prompts import (
        character_design,
        collect_materials,
        divide_events,
        doubter,
    )

    return {
        "collect_materials": collect_materials.PROMPT_VERSION,
        "doubter": doubter.PROMPT_VERSION,
        "divide_events": divide_events.PROMPT_VERSION,
        "character_design": character_design.PROMPT_VERSION,
    }


def legacy_progress(
    status: str,
    *,
    research_state: str = "pending",
    write_state: str = "pending",
    detail: str | None = None,
) -> GenerationProgress:
    """旧确定性合成路径的进度投影（#33 退役）：把 genre/research/generate/verify
    四阶段映射到 workflow 节点形状，保证前端只有一种进度契约。"""
    research_ok = research_state != "failed"
    node_status = GenerationNodeStatus(write_state) if write_state in (
        "running",
        "succeeded",
        "failed",
    ) else GenerationNodeStatus.PENDING
    return GenerationProgress(
        status=GenerationStatus(status),
        nodes=[
            NodeProgress(
                node=GenerationNode.COLLECT_MATERIALS,
                status=GenerationNodeStatus.SUCCEEDED if research_ok
                else GenerationNodeStatus.FAILED,
                detail="网络资料降级，纯原文生成" if research_state == "degraded" else None,
            ),
            NodeProgress(
                node=GenerationNode.VERIFY_MATERIALS,
                status=GenerationNodeStatus.SUCCEEDED if research_ok
                else GenerationNodeStatus.PENDING,
            ),
            NodeProgress(node=GenerationNode.DIVIDE_EVENTS, status=GenerationNodeStatus.PENDING),
            NodeProgress(
                node=GenerationNode.DESIGN_CHARACTERS, status=GenerationNodeStatus.PENDING
            ),
            NodeProgress(node=GenerationNode.WRITE_SCRIPT, status=node_status, detail=detail),
            NodeProgress(node=GenerationNode.FINAL_AUDIT, status=GenerationNodeStatus.PENDING),
        ],
    )


class ScriptLibrary:
    """可复用剧本的唯一业务入口（REST 之下）。"""

    def __init__(
        self,
        *,
        session_factory,
        script_llm=None,
        content_pipeline: ContentPipeline | None = None,
        rag: RagService | None = None,
        model_name: str = "",
        usage_recorder=None,
        workflow_checkpointer=None,
        workflow_enabled: bool = False,
    ) -> None:
        self._factory = session_factory
        self._script_llm = script_llm
        self._pipeline = content_pipeline or ContentPipeline()
        self._rag = rag
        self._model_name = model_name
        self._usage_recorder = usage_recorder
        self._workflow_checkpointer = workflow_checkpointer
        self._workflow_enabled = workflow_enabled
        self._tasks: dict[int, asyncio.Task] = {}

    # ===== 素材导入 =====

    async def import_material(
        self, actor: Actor, inp: MaterialInput, *, raw_bytes: bytes | None = None
    ) -> MaterialRecord:
        analysis = self._pipeline.analyze(inp, raw_bytes=raw_bytes)
        async with self._factory() as s:
            row = MaterialRecord(
                org_id=actor.org_id,
                owner_user_id=actor.user_id,
                raw_text=inp.raw_text,
                collection_output=analysis.model_dump(mode="json"),
            )
            s.add(row)
            await s.commit()
        return row

    async def get_material(self, material_id: int, actor: Actor) -> MaterialRecord:
        async with self._factory() as s:
            row = await s.get(MaterialRecord, material_id)
        if row is None or row.owner_user_id != actor.user_id:
            raise new(codes.SCR_MATERIAL_NOT_FOUND, extra={"id": material_id})
        return row

    # ===== 草稿创建 / 生成 =====

    async def create_script(
        self, actor: Actor, *, material_id: int, name: str, description: str | None
    ) -> ScriptRecord:
        await self.get_material(material_id, actor)
        async with self._factory() as s:
            row = ScriptRecord(
                org_id=actor.org_id,
                owner_user_id=actor.user_id,
                material_id=material_id,
                name=name.strip(),
                description=(description or None),
                status=ScriptStatus.DRAFT.value,
                visibility=ScriptVisibility.ORG.value,
            )
            s.add(row)
            await s.commit()
        return row

    def _is_running(self, script_id: int) -> bool:
        task = self._tasks.get(script_id)
        return task is not None and not task.done()

    async def _schedule_generation(self, script_id: int, script: ScriptRecord) -> None:
        """取消同 id 的在途任务，落一条 attempt 行并调度新生成（避免并发双写）。"""
        existing = self._tasks.get(script_id)
        if existing is not None and not existing.done():
            existing.cancel()
        attempt = ScriptGenerationRecord(
            script_id=script.id,
            org_id=script.org_id,
            owner_user_id=script.owner_user_id,
            thread_id=uuid.uuid4().hex,
            status=GenerationStatus.RUNNING.value,
            progress=legacy_progress("running").model_dump(mode="json"),
        )
        async with self._factory() as s:
            s.add(attempt)
            await s.commit()
        task = asyncio.create_task(
            self._run_generation(script.id, attempt.id, attempt.thread_id)
        )
        self._tasks[script.id] = task
        task.add_done_callback(
            lambda t, sid=script.id, aid=attempt.id: self._on_task_done(sid, t, aid)
        )

    def _on_task_done(
        self, script_id: int, task: asyncio.Task, attempt_id: int
    ) -> None:
        # 身份比较：避免误删同 id 的新任务引用（重复生成竞态，S2）
        if self._tasks.get(script_id) is task:
            self._tasks.pop(script_id, None)
        if task.cancelled():
            # 在途任务被取消（删除/重排）：attempt 显式标记失败，避免永远挂在 running。
            # fire-and-forget 须持有引用防 GC（S7）；行已被 CASCADE 删除时 _save_progress 自动跳过。
            cleanup = asyncio.get_running_loop().create_task(
                self._save_progress(
                    attempt_id,
                    status=GenerationStatus.FAILED.value,
                    error="cancelled",
                )
            )
            _background_tasks.add(cleanup)
            cleanup.add_done_callback(_background_tasks.discard)

    async def start_generation(self, script_id: int, actor: Actor) -> ScriptRecord:
        """校验并调度后台生成任务（非阻塞）；仅草稿可生成/重生。"""
        script = await self._load_owned(script_id, actor)
        self._require_editable(script)
        if not self._is_running(script_id):
            await self._schedule_generation(script_id, script)
        return script

    async def await_generation(self, script_id: int) -> None:
        """测试/内部用：等待后台生成任务完成。"""
        task = self._tasks.get(script_id)
        if task is not None:
            await task

    async def regenerate(self, script_id: int, actor: Actor) -> ScriptRecord:
        script = await self._load_owned(script_id, actor)
        self._require_editable(script)
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
            row.script_data = None
            row.verification = None
            await s.commit()
        await self._schedule_generation(script_id, script)
        return row

    # ===== attempt 进度（GenerationProgress 契约的落库面）=====

    async def _save_progress(
        self,
        attempt_id: int,
        *,
        status: str | None = None,
        progress: GenerationProgress | None = None,
        error: str | None = None,
    ) -> None:
        async with self._factory() as s:
            row = await s.get(ScriptGenerationRecord, attempt_id)
            if row is None:
                return
            if progress is not None:
                row.progress = progress.model_dump(mode="json")
                # B1：观测列与快照总体状态保持一致（sink 只带 progress 时也同步）
                if status is None:
                    status = progress.status.value
            if status is not None:
                row.status = status
                if progress is None:
                    # 仅翻转状态时同步快照里的总体状态
                    snapshot = GenerationProgress.model_validate(row.progress)
                    snapshot.status = GenerationStatus(status)
                    row.progress = snapshot.model_dump(mode="json")
            if error is not None:
                row.error = error
            await s.commit()

    async def progress(self, script_id: int) -> GenerationProgress | None:
        """最近一次生成尝试的进度快照；从未生成过返回 None。

        `row.error`（取消/错误码等终态信息）合入快照的 error 字段，
        保证教师端失败详情可见（S3）。
        """
        async with self._factory() as s:
            row = (
                await s.execute(
                    select(ScriptGenerationRecord)
                    .where(ScriptGenerationRecord.script_id == script_id)
                    .order_by(ScriptGenerationRecord.id.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
        if row is None:
            return None
        snapshot = GenerationProgress.model_validate(row.progress)
        if row.error and not snapshot.error:
            snapshot.error = row.error
        return snapshot

    # ===== 生成任务（workflow 主路径 / 旧合成路径）=====

    async def _run_generation(
        self, script_id: int, attempt_id: int, thread_id: str
    ) -> None:
        try:
            script, material, analysis = await self._load_generation_inputs(script_id)
            if self._workflow_enabled and self._script_llm is not None:
                await self._run_workflow(
                    script, material, analysis, attempt_id=attempt_id, thread_id=thread_id
                )
            elif self._script_llm is not None:
                await self._run_legacy_stage1(
                    script, analysis, attempt_id=attempt_id
                )
            else:
                await self._run_legacy_synth(script, analysis, attempt_id=attempt_id)
        except Exception as exc:
            logger.warning(
                "script_generation_failed script_id=%s reason=%s",
                script_id,
                getattr(exc, "code", exc),
            )
            await self._save_progress(
                attempt_id,
                status=GenerationStatus.FAILED.value,
                error=str(getattr(exc, "code", exc)),
            )

    async def _load_generation_inputs(
        self, script_id: int
    ) -> tuple[ScriptRecord, MaterialRecord, TextAnalysis]:
        async with self._factory() as s:
            script = await s.get(ScriptRecord, script_id)
            material = (
                await s.get(MaterialRecord, script.material_id)
                if script is not None and script.material_id is not None
                else None
            )
        if material is None:
            raise new(
                codes.SCR_MATERIAL_NOT_FOUND,
                extra={"id": getattr(script, "material_id", None)},
            )
        analysis = TextAnalysis.model_validate(material.collection_output)
        return script, material, analysis

    async def _run_workflow(
        self,
        script: ScriptRecord,
        material: MaterialRecord,
        analysis: TextAnalysis,
        *,
        attempt_id: int,
        thread_id: str,
    ) -> None:
        """LangGraph workflow：节点进度逐事件落库，终态写 scripts.script_data。"""
        web, _research_state = await self._research(analysis)
        nodes = WorkflowNodes(
            self._stage1_llm(script),
            model_name=self._model_name,
        )

        async def sink(snapshot: GenerationProgress) -> None:
            await self._save_progress(attempt_id, progress=snapshot)

        runner = WorkflowRunner(
            nodes,
            checkpointer=self._workflow_checkpointer,
            progress_sink=sink,
        )
        final = await runner.run(
            initial_state(
                script_id=script.id,
                session_id=f"script-{script.id}",
                analysis=analysis,
                web_evidence=web,
            ),
            thread_id=thread_id,
        )
        package = final.get("package")
        telemetry = dict(final.get("write_telemetry") or {})
        telemetry["doubter_rounds"] = len(runner.snapshot().doubter_events)
        telemetry["prompt_versions"] = _prompt_versions()
        await self._persist_package(script.id, package, telemetry)

    async def _run_legacy_stage1(
        self, script: ScriptRecord, analysis: TextAnalysis, *, attempt_id: int
    ) -> None:
        """旧 Stage1 单次生成路径（测试注入 fake LLM 时走此路径；#33 退役）。"""
        web, research_state = await self._research(analysis)
        outcome = await Stage1Generator(
            self._stage1_llm(script), model=self._model_name
        ).generate(
            analysis,
            web_evidence=web,
            session_id=f"script-{script.id}",
        )
        package, telemetry = outcome.script_package, outcome.telemetry
        await self._persist_package(script.id, package, _telemetry_dict(telemetry))
        await self._save_progress(
            attempt_id,
            status=GenerationStatus.SUCCEEDED.value,
            progress=legacy_progress(
                "succeeded", research_state=research_state, write_state="succeeded"
            ),
        )

    async def _run_legacy_synth(
        self, script: ScriptRecord, analysis: TextAnalysis, *, attempt_id: int
    ) -> None:
        """旧确定性合成路径（无 key；测试与 E2E 依赖，#33 退役）。"""
        web, research_state = await self._research(analysis)
        package = synthesize_script_package(analysis)
        telemetry = GenerationTelemetry(
            model="deterministic",
            prompt_version=PROMPT_VERSION,
            schema_version=package.schema_version,
            latency_ms=0,
            token_count=0,
            retries=0,
        )
        # 计量不依赖真实 provider：无 key 合成路径同样按 stage1 用途
        # 入账一条 llm_usage（#22 验收），否则 CI 全新库的用量看板为空。
        if self._usage_recorder is not None:
            from app.infrastructure.usage import UsageContext

            await self._usage_recorder.record(
                UsageContext(
                    org_id=script.org_id,
                    user_id=script.owner_user_id,
                    script_id=script.id,
                ),
                provider="deterministic",
                model="deterministic",
                purpose=UsagePurpose.STAGE1,
                messages=[{"role": "user", "content": ""}],
                completion=package.model_dump_json(),
            )
        await self._persist_package(script.id, package, _telemetry_dict(telemetry))
        await self._save_progress(
            attempt_id,
            status=GenerationStatus.SUCCEEDED.value,
            progress=legacy_progress(
                "succeeded", research_state=research_state, write_state="succeeded"
            ),
        )

    async def _persist_package(
        self, script_id: int, package, telemetry: dict
    ) -> None:
        """写 scripts.script_data（竞态防护：仅草稿可写）。"""
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
            # 竞态防护：若生成期间剧本已被发布/下架/删除，丢弃结果，绝不覆盖
            if row is None or row.status != ScriptStatus.DRAFT.value:
                raise new(
                    codes.SCR_NOT_EDITABLE,
                    extra={"id": script_id, "status": getattr(row, "status", None)},
                )
            row.script_data = package.model_dump(mode="json")
            row.verification = telemetry
            await s.commit()

    def _stage1_llm(self, script: ScriptRecord) -> object:
        """按剧本归属上下文包装 LLM，使逐次调用写入 llm_usage（#22）。"""
        if self._usage_recorder is None:
            return self._script_llm
        from app.infrastructure.usage import UsageContext

        return self._usage_recorder.wrap(
            self._script_llm,
            UsageContext(
                org_id=script.org_id,
                user_id=script.owner_user_id,
                script_id=script.id,
            ),
        )

    async def _research(self, analysis: TextAnalysis):
        if self._rag is None:
            return [], "degraded"
        query = analysis.title or "、".join(c.name for c in analysis.characters[:3])
        web = await self._rag.research(query or analysis.genre.genre.value)
        return web, ("succeeded" if web else "degraded")

    # ===== 发布 / 下架 / 删除 =====

    async def publish(
        self, script_id: int, actor: Actor, visibility: ScriptVisibility
    ) -> ScriptRecord:
        script = await self._load_owned(script_id, actor)
        if script.script_data is None:
            raise new(codes.SCR_NOT_EDITABLE, extra={"id": script_id, "status": script.status})
        if script.status == ScriptStatus.PUBLISHED.value:
            # 已发布：仅允许改可见性（核心内容不可变）
            return await self._set_status(
                script_id, status=None, visibility=visibility.value
            )
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
            row.status = ScriptStatus.PUBLISHED.value
            row.visibility = visibility.value
            await s.commit()
            return row

    async def unpublish(self, script_id: int, actor: Actor) -> ScriptRecord:
        script = await self._load_owned(script_id, actor)
        if script.status != ScriptStatus.PUBLISHED.value:
            raise new(
                codes.SCR_NOT_EDITABLE, extra={"id": script_id, "status": script.status}
            )
        return await self._set_status(
            script_id, status=ScriptStatus.UNPUBLISHED.value, visibility=None
        )

    async def delete(self, script_id: int, actor: Actor) -> None:
        script = await self._load_owned(script_id, actor)
        if script.status != ScriptStatus.DRAFT.value:
            raise new(
                codes.SCR_NOT_EDITABLE, extra={"id": script_id, "status": script.status}
            )
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
            if row is not None:
                await s.delete(row)
                await s.commit()
        task = self._tasks.pop(script_id, None)
        if task is not None and not task.done():
            task.cancel()

    # ===== 查询 =====

    async def list_scripts(self, actor: Actor) -> list[ScriptRecord]:
        async with self._factory() as s:
            rows = (
                await s.execute(
                    select(ScriptRecord)
                    .where(ScriptRecord.owner_user_id == actor.user_id)
                    .order_by(ScriptRecord.updated_at.desc())
                )
            ).scalars().all()
        return list(rows)

    async def list_visible(self, actor: Actor) -> list[ScriptRecord]:
        """剧本广场（#21）：已发布且可见（同 org 或 public）的剧本，任意登录用户可浏览。

        SQL 与 `app.domain.access.script_visible_to` 的非 owner 分支等价；可见性判定以 access 为准。
        """
        async with self._factory() as s:
            rows = (
                await s.execute(
                    select(ScriptRecord)
                    .where(
                        ScriptRecord.status == ScriptStatus.PUBLISHED.value,
                        or_(
                            ScriptRecord.visibility == ScriptVisibility.PUBLIC.value,
                            ScriptRecord.org_id == actor.org_id,
                        ),
                    )
                    .order_by(ScriptRecord.updated_at.desc())
                )
            ).scalars().all()
        return list(rows)

    async def get_script(self, script_id: int, actor: Actor) -> ScriptRecord:
        """按可见性读取：owner 全量；他人仅已发布（org 同 org / public 跨 org）。"""
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
        if row is None or not script_visible_to(actor, row):
            raise new(codes.SCR_NOT_FOUND, extra={"id": script_id})
        return row

    # ===== 内部工具 =====

    async def _load_owned(self, script_id: int, actor: Actor) -> ScriptRecord:
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
        if row is None:
            raise new(codes.SCR_NOT_FOUND, extra={"id": script_id})
        if row.owner_user_id != actor.user_id:
            raise new(codes.AUTH_FORBIDDEN, extra={"reason": "not script owner"})
        return row

    @staticmethod
    def _require_editable(script: ScriptRecord) -> None:
        if script.status != ScriptStatus.DRAFT.value:
            raise new(
                codes.SCR_NOT_EDITABLE,
                extra={"id": script.id, "status": script.status},
            )

    async def _set_status(self, script_id: int, *, status, visibility):
        async with self._factory() as s:
            row = await s.get(ScriptRecord, script_id)
            if status is not None:
                row.status = status
            if visibility is not None:
                row.visibility = visibility
            await s.commit()
            return row


__all__ = ["ScriptLibrary", "legacy_progress"]
