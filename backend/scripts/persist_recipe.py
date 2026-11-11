# 把本地演练产物（local-run-out/<RUN_NAME>）落成已发布剧本，供前端直接开演。
# 直接写行而不走 ScriptLibraryService._persist_package：后者会重跑
# validate_replay，本地演练版带着已知的非阻断 issue（分支说话人越界），会被拒。
# 用法: cd backend && uv run python -m scripts.persist_recipe
from __future__ import annotations

import asyncio
import json
import logging
import uuid as uuid_mod
from pathlib import Path

RUN_NAME = "beiying"
REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "local-run-out" / RUN_NAME
TEXT_PATH = REPO / "etc" / "背影.txt"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("scripts.persist_recipe")


async def main() -> int:
    from sqlalchemy import select, update

    from app.contracts.material import MaterialInput, MaterialSource
    from app.domain.content.pipeline import ContentPipeline
    from app.infrastructure.db.session import SessionLocal
    from app.infrastructure.models.asset import Asset
    from app.infrastructure.models.material import Material
    from app.infrastructure.models.org import Org
    from app.infrastructure.models.script import Script
    from app.infrastructure.models.user import User

    pkg = json.loads((SRC / "script.json").read_text(encoding="utf-8"))
    text = TEXT_PATH.read_text(encoding="utf-8")
    analysis = ContentPipeline().analyze(
        MaterialInput(source=MaterialSource.PASTE, raw_text=text)
    )

    async with SessionLocal() as s:
        org = (await s.execute(select(Org).limit(1))).scalar_one_or_none()
        teacher = (
            await s.execute(
                select(User).where(User.role == "teacher").order_by(User.id).limit(1)
            )
        ).scalar_one_or_none()
        if org is None or teacher is None:
            log.error("缺少 org 或 teacher，先 make seed")
            return 2

        material = Material(
            org_id=org.id,
            owner_user_id=teacher.id,
            raw_text=text,
            collection_output=analysis.model_dump(mode="json"),
        )
        s.add(material)
        await s.commit()
        await s.refresh(material)

        script = Script(
            org_id=org.id,
            owner_user_id=teacher.id,
            material_id=material.id,
            name=pkg.get("title") or "本地演练剧本",
            description="本地演练：真实 LLM workflow 生成（teacher_gates 关闭，审核放宽）",
            status="published",
            visibility="org",
            script_data=pkg,
            verification={"source": "local-run", "run": RUN_NAME},
        )
        s.add(script)
        await s.commit()
        await s.refresh(script)

        # 资产归属改到真实剧本名下（此前挂在 script_id=0）：AssetAccessService
        # 按脚本鉴权，挂在 0 上会 404/403。
        ids = []
        for sc in pkg.get("scenes", []):
            if sc.get("background_asset"):
                ids.append(sc["background_asset"]["asset_id"])
            for br in sc.get("branches", []):
                a = br.get("background_asset")
                if isinstance(a, dict):
                    ids.append(a["asset_id"])
        for ch in pkg.get("characters", []):
            a = ch.get("avatar_asset")
            if isinstance(a, dict):
                ids.append(a["asset_id"])
        res = await s.execute(
            update(Asset)
            .where(Asset.asset_id.in_([uuid_mod.UUID(i) for i in ids]))
            .values(script_id=script.id)
        )
        await s.commit()
        log.info(
            "material=%s script=%s「%s」assets 改归属 %s 行",
            material.id, script.id, script.name, res.rowcount,
        )
        print(f"SCRIPT_ID={script.id}")
    return 0


raise SystemExit(asyncio.run(main()))
