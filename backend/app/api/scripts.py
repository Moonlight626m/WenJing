"""剧本库 REST 路由（issue #19 / ADR-0002 §3）：教师创作 API。

薄协议层：鉴权/角色 → 委托 `ScriptLibrary` → 契约投影。错误经全局 `WJError` 处理器。
创作/发布类端点要求 `teacher`；读取详情按可见性放行任意登录用户（供 #21 学生端复用）。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.auth.deps import Principal, require_role
from app.config import get_settings
from app.contracts.content import TextAnalysis
from app.contracts.enums import UserRole
from app.contracts.material import MaterialInput
from app.contracts.script import ScriptPackage
from app.contracts.script_library import (
    MaterialPublic,
    ScriptCreateRequest,
    ScriptDetail,
    ScriptListResponse,
    ScriptPublishRequest,
    ScriptSummary,
)
from app.models.script import Script as ScriptRecord
from app.scripts.service import ScriptLibrary

router = APIRouter(prefix="/api", tags=["scripts"])

_library: ScriptLibrary | None = None


def get_script_library() -> ScriptLibrary:
    """进程级 ScriptLibrary 单例（与 SessionApplication 同源 LLM 配置）。"""
    global _library
    if _library is None:
        from app.agents.model_config import ModelServiceFactory
        from app.db.session import SessionLocal
        from app.rag.service import RagService

        settings = get_settings()
        script_llm = None
        if settings.llm_api_key:
            try:
                script_llm = ModelServiceFactory.build(settings.llm_model_config())
            except Exception:
                script_llm = None
        _library = ScriptLibrary(
            session_factory=SessionLocal,
            script_llm=script_llm,
            rag=RagService(),
            model_name=settings.llm_model,
        )
    return _library


_Teacher = Annotated[Principal, Depends(require_role(UserRole.TEACHER))]
_Viewer = Annotated[
    Principal,
    Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TEACHER, UserRole.STUDENT)),
]


def _summary(row: ScriptRecord) -> ScriptSummary:
    return ScriptSummary(
        id=row.id,
        name=row.name,
        description=row.description,
        status=row.status,
        visibility=row.visibility,
        material_id=row.material_id,
        owner_user_id=row.owner_user_id,
        org_id=row.org_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _detail(library: ScriptLibrary, row: ScriptRecord, actor) -> ScriptDetail:
    package = ScriptPackage.model_validate(row.script_data) if row.script_data else None
    # 生成进度仅对 owner 可见（含失败详情）；他人读取已发布剧本时不暴露
    generation = library.progress(row.id) if row.owner_user_id == actor.user_id else None
    return ScriptDetail(
        script=_summary(row),
        package=package,
        generation=generation,
    )


# ===== 素材 =====


@router.post("/materials", status_code=201, response_model=MaterialPublic)
async def import_material(
    body: MaterialInput,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> MaterialPublic:
    """导入课文素材（教师）：真实 ingestion 校验 + 原文分析，独立归属。"""
    row = await library.import_material(principal.actor, body)
    analysis = TextAnalysis.model_validate(row.collection_output)
    return MaterialPublic(
        id=row.id,
        title=analysis.title,
        content_hash=analysis.content_hash,
        char_count=len(row.raw_text),
        created_at=row.created_at,
    )


# ===== 剧本 =====


@router.post("/scripts", status_code=201, response_model=ScriptSummary)
async def create_script(
    body: ScriptCreateRequest,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptSummary:
    """从素材创建剧本草稿（待生成）。"""
    row = await library.create_script(
        principal.actor,
        material_id=body.material_id,
        name=body.name,
        description=body.description,
    )
    return _summary(row)


@router.get("/scripts", response_model=ScriptListResponse)
async def list_scripts(
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptListResponse:
    """教师剧本库：当前教师自有的全部剧本（含草稿）。"""
    rows = await library.list_scripts(principal.actor)
    return ScriptListResponse(items=[_summary(r) for r in rows])


@router.get("/scripts/{script_id}", response_model=ScriptDetail)
async def get_script(
    script_id: int,
    principal: _Viewer,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptDetail:
    """剧本详情：owner 全量；他人仅已发布（org 同 org / public 跨 org）。"""
    row = await library.get_script(script_id, principal.actor)
    return _detail(library, row, principal.actor)


@router.post("/scripts/{script_id}/generate", status_code=202, response_model=ScriptDetail)
async def generate_script(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptDetail:
    """启动异步生成（进程内任务 + 内存进度）；前端轮询详情。"""
    row = await library.start_generation(script_id, principal.actor)
    return _detail(library, row, principal.actor)


@router.post(
    "/scripts/{script_id}/regenerate", status_code=202, response_model=ScriptDetail
)
async def regenerate_script(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptDetail:
    """清除草稿内容并重新生成（仅草稿）。"""
    row = await library.regenerate(script_id, principal.actor)
    return _detail(library, row, principal.actor)


@router.post("/scripts/{script_id}/publish", response_model=ScriptSummary)
async def publish_script(
    script_id: int,
    body: ScriptPublishRequest,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptSummary:
    """发布（org/public）；发布后核心内容不可编辑，仅可改可见性/下架。"""
    row = await library.publish(script_id, principal.actor, body.visibility)
    return _summary(row)


@router.post("/scripts/{script_id}/unpublish", response_model=ScriptSummary)
async def unpublish_script(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptSummary:
    """下架：不再进库，存量世界可继续。"""
    row = await library.unpublish(script_id, principal.actor)
    return _summary(row)


@router.delete("/scripts/{script_id}", status_code=204)
async def delete_script(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> None:
    """删除草稿（已发布/下架不可删）。"""
    await library.delete(script_id, principal.actor)


__all__ = ["router", "get_script_library"]
