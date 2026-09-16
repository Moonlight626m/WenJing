"""剧本库应用服务（issue #19 / ADR-0002 §3–4）。

- 教师：导入素材 → 建草稿 → 异步生成（进程内 asyncio 任务 + 内存进度，轮询）→
  发布（org/public）/下架 → 删除/重新生成。
- 归属：素材与剧本独立归属 owner/org；仅 owner 可变更，已发布剧本对同 org
  （或跨 org 公开）只读可见。
- 生成不落「进行中」状态：进程重启丢在途生成，由教师重新生成（已知代价）。
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import or_, select

from app.access import Actor, script_visible_to
from app.content.pipeline import ContentPipeline
from app.contracts.content import TextAnalysis
from app.contracts.enums import ScriptStatus, ScriptVisibility, UsagePurpose
from app.contracts.material import MaterialInput
from app.errx import codes, new
from app.generation.stage1 import (
    PROMPT_VERSION,
    GenerationTelemetry,
    Stage1Generator,
    synthesize_script_package,
)
from app.models.material import Material as MaterialRecord
from app.models.script import Script as ScriptRecord
from app.rag.service import RagService

_GENERATION_PHASES = ("genre", "research", "generate", "verify")

logger = logging.getLogger("wenjing.scripts.library")


def generation_progress(
    status: str, phase_states: dict | None = None, *, detail: str | None = None
) -> dict:
    """生成进度快照（status: idle|running|succeeded|failed）。"""
    phase_state = {
        "genre": "pending",
        "research": "pending",
        "generate": "pending",
        "verify": "pending",
    }
    phase_state.update(phase_states or {})
    if status == "running":
        phase_state["generate"] = "running"
    elif status == "succeeded":
        phase_state |= {
            "genre": "succeeded",
            "generate": "succeeded",
            "verify": "succeeded",
        }
    elif status == "failed":
        phase_state["generate"] = "failed"
    return {
        "status": status,
        "phases": [
            {"name": name, "state": phase_state[name], "detail": detail}
            for name in _GENERATION_PHASES
        ],
    }


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
    ) -> None:
        self._factory = session_factory
        self._script_llm = script_llm
        self._pipeline = content_pipeline or ContentPipeline()
        self._rag = rag
        self._model_name = model_name
        self._usage_recorder = usage_recorder
        self._progress: dict[int, dict] = {}
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
            await s.flush()
            # 表 identity 复位后 id 可能复用：清理同 id 的历史进度，避免串扰
            self._progress.pop(row.id, None)
            self._tasks.pop(row.id, None)
            await s.commit()
        return row

    def _is_running(self, script_id: int) -> bool:
        task = self._tasks.get(script_id)
        return task is not None and not task.done()

    def _schedule_generation(self, script_id: int) -> None:
        """取消同 id 的在途任务并调度新生成（避免并发双写）。"""
        existing = self._tasks.get(script_id)
        if existing is not None and not existing.done():
            existing.cancel()
        self._progress[script_id] = generation_progress("running")
        task = asyncio.create_task(self._run_generation(script_id))
        self._tasks[script_id] = task
        task.add_done_callback(lambda _t, sid=script_id: self._tasks.pop(sid, None))

    async def start_generation(self, script_id: int, actor: Actor) -> ScriptRecord:
        """校验并调度后台生成任务（非阻塞）；仅草稿可生成/重生。"""
        script = await self._load_owned(script_id, actor)
        self._require_editable(script)
        if not self._is_running(script_id):
            self._schedule_generation(script_id)
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
        self._schedule_generation(script_id)
        return row

    async def _run_generation(self, script_id: int) -> None:
        self._progress[script_id] = generation_progress("running")
        research_state = "degraded"
        try:
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
            web, research_state = await self._research(analysis)
            self._progress[script_id] = generation_progress(
                "running", {"genre": "succeeded", "research": research_state}
            )
            if self._script_llm is None:
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
                if self._usage_recorder is not None and script is not None:
                    from app.usage import UsageContext

                    await self._usage_recorder.record(
                        UsageContext(
                            org_id=script.org_id,
                            user_id=script.owner_user_id,
                            script_id=script.id,
                        ),
                        provider="deterministic",
                        model="deterministic",
                        purpose=UsagePurpose.STAGE1,
                        messages=[{"role": "user", "content": material.raw_text}],
                        completion=package.model_dump_json(),
                    )
            else:
                outcome = await Stage1Generator(
                    self._stage1_llm(script), model=self._model_name
                ).generate(
                    analysis,
                    web_evidence=web,
                    session_id=f"script-{script_id}",
                )
                package, telemetry = outcome.script_package, outcome.telemetry

            async with self._factory() as s:
                row = await s.get(ScriptRecord, script_id)
                # 竞态防护：若生成期间剧本已被发布/下架/删除，丢弃结果，绝不覆盖
                if row is None or row.status != ScriptStatus.DRAFT.value:
                    self._progress[script_id] = generation_progress(
                        "failed", detail="script is no longer a draft"
                    )
                    return
                row.script_data = package.model_dump(mode="json")
                row.verification = {
                    "model": telemetry.model,
                    "prompt_version": telemetry.prompt_version,
                    "schema_version": telemetry.schema_version,
                    "latency_ms": telemetry.latency_ms,
                    "token_count": telemetry.token_count,
                    "retries": telemetry.retries,
                }
                await s.commit()
            self._progress[script_id] = generation_progress(
                "succeeded", {"research": research_state}
            )
        except Exception as exc:
            logger.warning(
                "script_generation_failed script_id=%s reason=%s",
                script_id,
                getattr(exc, "code", exc),
            )
            self._progress[script_id] = generation_progress(
                "failed", detail=str(getattr(exc, "code", exc))
            )

    def _stage1_llm(self, script: ScriptRecord) -> object:
        """按剧本归属上下文包装 Stage1 LLM，使逐次调用写入 llm_usage（#22）。"""
        if self._usage_recorder is None:
            return self._script_llm
        from app.usage import UsageContext

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
        self._progress.pop(script_id, None)

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

        SQL 与 `app.access.script_visible_to` 的非 owner 分支等价；可见性判定以 access 为准。
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

    def progress(self, script_id: int) -> dict | None:
        return self._progress.get(script_id)

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


__all__ = ["ScriptLibrary", "generation_progress"]
