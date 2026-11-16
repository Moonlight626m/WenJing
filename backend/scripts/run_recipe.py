# 本地演练驱动：直接跑真实 workflow（真实 LLM + 真实配图），不落剧本库、
# 无人工介入（教师闸门节点内跳过）。过程日志走两条通道：
# 1) progress_sink：每条命令结束时打印全部节点状态（runner 投影）；
# 2) progress_hook：节点内子进度（配图 1/N、角色扇出等）实时打印。
# 用法: cd backend && uv run python -m scripts.run_recipe
# 产物: <repo>/local-run-out/<RUN_NAME>/ 下 script.json + progress.json + 图片。
from __future__ import annotations

import asyncio
import json
import logging
import uuid as uuid_mod
from pathlib import Path

RUN_NAME = "beiying"
REPO = Path(__file__).resolve().parents[2]
TEXT_PATH = REPO / "etc" / "背影.txt"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    datefmt="%H:%M:%S",
)
# 只静音最吵的两类；LLM 调用层（wenjing.agents.llm 的
# llm_call_start/end / llm_stream_start/end）保持 INFO 可见。
for name in ("wenjing.app", "sqlalchemy.engine", "wenjing.agents.model_config"):
    logging.getLogger(name).setLevel(logging.WARNING)
logging.getLogger("wenjing.app").propagate = False  # engine echo=True 直挂 root


def _show_wj_extra(record: logging.LogRecord) -> bool:
    """把 wj_extra 字典展开进消息，便于肉眼看每次 LLM 调用的明细。"""
    extra = getattr(record, "wj_extra", None)
    if isinstance(extra, dict) and extra:
        record.msg = f"{record.msg} {json.dumps(extra, ensure_ascii=False, default=str)}"
    return True


logging.getLogger("wenjing").addFilter(_show_wj_extra)

log = logging.getLogger("scripts.run_recipe")

OUT = REPO / "local-run-out" / RUN_NAME
OUT.mkdir(parents=True, exist_ok=True)
TEXT = TEXT_PATH


async def main() -> int:
    from sqlalchemy import select

    from app.composition import get_container
    from app.contracts.material import MaterialInput, MaterialSource
    from app.domain.content.pipeline import ContentPipeline
    from app.domain.generation.workflow import (
        WorkflowNodes,
        WorkflowRunner,
        initial_state,
    )
    from app.infrastructure.config import get_settings
    from app.infrastructure.db.session import SessionLocal
    from app.infrastructure.llm.factory import ModelServiceFactory
    from app.infrastructure.models.asset import Asset
    from app.infrastructure.models.org import Org

    settings = get_settings()
    text = TEXT.read_text(encoding="utf-8")
    log.info("material %s (%d chars), model=%s", TEXT, len(text), settings.llm_model)
    analysis = ContentPipeline().analyze(
        MaterialInput(source=MaterialSource.PASTE, raw_text=text)
    )
    log.info(
        "analyze: title=%s genre=%s characters=%d scenes=%d key_events=%d",
        analysis.title,
        analysis.genre.genre.value,
        len(analysis.characters),
        len(analysis.scenes),
        len(analysis.key_events),
    )

    async with SessionLocal() as s:
        org = (await s.execute(select(Org).limit(1))).scalar_one_or_none()
    if org is None:
        log.error("no org row; aborting")
        return 2
    org_id = str(org.id)
    log.info("org=%s", org_id)

    container = get_container()
    llm = ModelServiceFactory.build(settings.llm_model_config())
    designer = container.scene_designer

    async def sub_progress(node: str, detail: str) -> None:
        """节点内子进度：配图 N/M、角色扇出等，实时打印。"""
        log.info("[sub:%s] %s", node, detail)

    async def sink(snapshot) -> None:  # noqa: ANN001 - GenerationProgress
        """每次进度投影变化时打印当前各节点状态与 doubter 事件。"""
        states = " | ".join(
            f"{n.node.value}:{n.status.value}" for n in snapshot.nodes
        )
        log.info("[progress] %s", states)
        for ev in snapshot.doubter_events:
            log.info(
                "[doubter r%s] %s: %s", ev.round, ev.node.value, ev.verdict
            )

    nodes = WorkflowNodes(
        llm, model_name=settings.llm_model, scene_designer=designer
    )  # teacher_gates=False：三道闸门在节点级跳过，拓扑不变
    nodes.set_progress_hook(sub_progress)
    # 本地演练放宽审核：总审最多打回 2 次，第 3 版直接放行（不再 fail）。
    # 打回意见仍然写进 audit_issues，worker 侧可见「带着哪些问题通过」。
    from app.domain.generation.workflow import nodes as _wf_nodes

    _original_route = _wf_nodes.WorkflowNodes.route_after_audit

    def _relaxed_route(self, state):  # noqa: ANN001
        verdict = state.get("audit_verdict", "pass")
        if verdict == "reject" and int(state.get("write_retries", 0)) >= 2:
            log.info(
                "[relaxed] 总审打回已达 %d 次上限，放行当前版本（issues=%d 条）",
                state.get("write_retries", 0),
                len(state.get("audit_issues") or []),
            )
            return "design_exploration"
        return _original_route(self, state)

    _wf_nodes.WorkflowNodes.route_after_audit = _relaxed_route
    # 内存 checkpointer：runner 收尾会用 aget_state 回读终态通道（resume 兜底），
    # 没有 checkpointer 会抛 "No checkpointer set"。本地演练不需要持久化断点，
    # MemorySaver 足够；生产侧用 AsyncPostgresSaver（Container.open 装配）。
    from langgraph.checkpoint.memory import MemorySaver

    runner = WorkflowRunner(nodes, checkpointer=MemorySaver(), progress_sink=sink)
    log.info("workflow starting (thread=run-out-%s)", RUN_NAME)
    state = initial_state(
        script_id=0,  # 不落剧本库；资产归属 org 计量可落库
        session_id="run-out",
        analysis=analysis,
        web_evidence=[],
        org_id=org_id,
        user_id=org_id,
    )
    final = await runner.run(state, thread_id=f"run-out-{RUN_NAME}")
    log.info("workflow finished")

    package = final.get("package")
    if package is None:
        log.error("no package; FAILED")
        return 2
    pkg = package if isinstance(package, dict) else package.model_dump(mode="json")
    (OUT / "script.json").write_text(
        json.dumps(pkg, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    log.info("script.json written: %s scenes, %s characters",
             len(pkg.get("scenes", [])), len(pkg.get("characters", [])))
    snap = runner.snapshot()
    (OUT / "progress.json").write_text(
        json.dumps(snap.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    log.info("nodes: %s",
             [f"{n.node.value}:{n.status.value}" for n in snap.nodes])
    for ev in snap.doubter_events:
        log.info("doubter[r%s] %s: %s", ev.round, ev.node.value, ev.verdict)

    summary = final.get("asset_summary") or {}
    log.info("asset_summary: %s", summary)

    # 从 assets 表按 id 找 object_key，从 MinIO 下载字节
    ids: list[str] = []
    for scene in pkg.get("scenes", []):
        if scene.get("background_asset"):
            ids.append(scene["background_asset"]["asset_id"])
        for br in scene.get("branches", []):
            if br.get("background_asset") and isinstance(
                br["background_asset"], dict
            ):
                ids.append(br["background_asset"]["asset_id"])
    for ch in pkg.get("characters", []):
        if ch.get("avatar_asset") and isinstance(ch["avatar_asset"], dict):
            ids.append(ch["avatar_asset"]["asset_id"])
    log.info("asset ids (%d): %s", len(ids), ids)
    if not ids:
        log.warning("no assets referenced in package; skip download")
        return 0

    async with SessionLocal() as s:
        rows = (
            await s.execute(
                select(Asset).where(Asset.asset_id.in_([uuid_mod.UUID(i) for i in ids]))
            )
        ).scalars().all()
    import boto3
    from botocore.config import Config

    client = boto3.client(
        "s3",
        endpoint_url=settings.media_storage_endpoint or None,
        aws_access_key_id=settings.media_storage_access_key or None,
        aws_secret_access_key=settings.media_storage_secret_key or None,
        region_name=settings.media_storage_region or "us-east-1",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    for r in rows:
        if r.status != "ready":
            log.warning("asset %s status=%s, skip", r.asset_id, r.status)
            continue
        data = client.get_object(Bucket=settings.media_storage_bucket, Key=r.object_key)[
            "Body"
        ].read()
        # Asset 表不存 content_type；扩展名从 object_key（…/original.webp）推
        ext = r.object_key.rsplit(".", 1)[-1] if "." in r.object_key else "webp"
        label = r.dedup_key or str(r.asset_id)
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in label)[-80:]
        path = f"{r.kind}-{safe}.{ext}"
        (OUT / path).write_bytes(data)
        log.info("downloaded %s (%d bytes)", path, len(data))

    log.info("done: out dir %s", OUT)
    return 0


raise SystemExit(asyncio.run(main()))
