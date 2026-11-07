"""一次性补图：对已入库剧本（script_data）重跑 design_assets 节点并回写。

用途：Ark adapter 的 sequential_image_generation bug 修复后，为文本已定稿、
配图全失败的剧本（如 run5 的 script 2）补一次配图。幂等：SceneDesigner
按去重键缓存，FAILED 的旧票据不会命中，只有新 READY 才写回。
"""

from __future__ import annotations

import asyncio
import sys
import uuid

sys.path.insert(0, ".")

SCRIPT_ID = 2


async def main() -> int:
    from sqlalchemy import select

    from app.composition import get_container
    from app.domain.generation.workflow.nodes import WorkflowNodes
    from app.infrastructure.llm.factory import ModelServiceFactory
    from app.infrastructure.models.script import Script as ScriptRecord
    from app.infrastructure.models.org import Org

    container = get_container()
    await container.open()
    library = container.script_library

    async with container.session_factory() as s:
        script = (
            await s.execute(
                select(ScriptRecord).where(ScriptRecord.id == SCRIPT_ID)
            )
        ).scalar_one()
        org = (await s.execute(select(Org).limit(1))).scalar_one()
    org_id = str(org.id)

    from app.contracts.script import ScriptPackage
    import json

    data = script.script_data
    if isinstance(data, str):
        data = json.loads(data)
    package = ScriptPackage.model_validate(data)

    settings = container.settings
    designer = container.scene_designer
    nodes = WorkflowNodes(
        ModelServiceFactory.build(settings.llm_model_config()),
        model_name=settings.llm_model,
        scene_designer=designer,
    )
    state = {
        "package": package,
        "org_id": org_id,
        "user_id": org_id,
        "script_id": SCRIPT_ID,
        "dossier": None,
    }

    out = await nodes.design_assets(state)
    print("asset_summary:", out.get("asset_summary"))
    updated = out["package"]

    await library._persist_package(SCRIPT_ID, updated, script.verification or {})
    bg = sum(1 for s_ in updated.scenes if s_.background_asset is not None)
    br = sum(
        1
        for s_ in updated.scenes
        for b in s_.branches
        if b.background_asset is not None
    )
    av = sum(1 for c in updated.characters if c.avatar_asset is not None)
    print(
        f"persisted: bg {bg}/{len(updated.scenes)},"
        f" branches {br}, avatars {av}/{len(updated.characters)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
