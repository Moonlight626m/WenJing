"""一次性驱动：用真实课文《背影》走完 生成 workflow（含教师闸门）并入库。

走 ScriptLibrary 服务路径（与 REST 等价）：import_material → create_script →
start_generation → 每逢 awaiting_review 以默认 approve 恢复 → _persist_package。
"""

from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path

sys.path.insert(0, ".")

BACKOFF = 8.0
MAX_POLLS = 240  # BACKOFF * MAX_POLLS ≈ 32 分钟预算

GATE_DIRECTIVES: dict[str, list[str]] = {
    "materials": [],
    "pre_write": [],
    "final": [],
}


async def main() -> int:
    from app.composition import get_container
    from app.contracts.enums import UserRole
    from app.contracts.generation import GenerationStatus
    from app.contracts.material import MaterialInput, MaterialSource
    from app.contracts.script_library import GenerationResumeRequest
    from app.domain.access import Actor
    from app.infrastructure.config import get_settings

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    settings = get_settings()
    if not settings.llm_api_key:
        print("no LLM key, abort")
        return 1

    text = Path("/home/moonlight/projects/WenJing/etc/背影.txt").read_text(encoding="utf-8")

    container = get_container()
    await container.open()  # 事件循环内创建 checkpointer + 资产任务恢复
    library = container.script_library

    # 种子身份现场取（DB 可能被重建过，写死 UUID 会失效）
    import sqlalchemy as _sa

    async with container.session_factory() as s:
        org_row = (await s.execute(_sa.text("select id from orgs limit 1"))).scalar_one()
        user_row = (
            await s.execute(
                _sa.text("select id from users where role='teacher' limit 1")
            )
        ).scalar_one()
    org_id = uuid.UUID(str(org_row))
    teacher_id = uuid.UUID(str(user_row))
    actor = Actor(user_id=teacher_id, org_id=org_id, role=UserRole.TEACHER)

    print("== import_material ==")
    material = await library.import_material(
        actor,
        MaterialInput(source=MaterialSource.PASTE, filename="背影.txt", raw_text=text),
    )
    print(f"material id={material.id}")

    print("== create_script ==")
    script = await library.create_script(
        actor, material_id=material.id, name="背影", description="朱自清《背影》课文情景演绎"
    )
    print(f"script id={script.id}")

    print("== start_generation ==")
    script = await library.start_generation(script.id, actor)

    attempt_seen_running = False
    for i in range(MAX_POLLS):
        await asyncio.sleep(BACKOFF)
        progress = await library.progress(script.id)
        if progress is None:
            print(f"[poll {i}] no progress yet")
            continue
        nodes = " ".join(
            f"{n.node.value}:{n.status.value}" + (f"({n.detail})" if n.detail else "")
            for n in progress.nodes
        )
        print(f"[poll {i}] status={progress.status.value} | {nodes}")
        if progress.status == GenerationStatus.AWAITING_REVIEW:
            review = await library.review(script.id)
            gate = str(review.gate) if review else "materials"
            print(f"== gate hit: {gate} ==")
            await library.resume_generation(
                script.id,
                actor,
                resume=GenerationResumeRequest(
                    directives=GATE_DIRECTIVES.get(str(gate), []),
                    action="approve",
                ),
            )
            print("== resumed ==")
            attempt_seen_running = False
        elif progress.status == GenerationStatus.SUCCEEDED:
            print("== succeeded ==")
            return 0
        elif progress.status == GenerationStatus.FAILED:
            print(f"== FAILED: {progress.error}")
            return 2
    print("poll budget exhausted")
    return 3


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
