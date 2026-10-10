"""剧本库 REST 路由（issue #19 / ADR-0002 §3）：教师创作 API。

薄协议层：鉴权/角色 → 委托 `ScriptLibrary` → 契约投影。错误经全局 `WJError` 处理器。
创作/发布类端点要求 `teacher`；读取详情按可见性放行任意登录用户（供 #21 学生端复用）。
"""

import asyncio
import json
from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import StreamingResponse

from app.composition import get_container
from app.contracts.content import TextAnalysis
from app.contracts.enums import UserRole
from app.contracts.material import MaterialInput
from app.contracts.review import validate_subject_key
from app.contracts.script import AssetRef, ScriptPackage
from app.contracts.script_library import (
    GenerationResumeRequest,
    MaterialPublic,
    ScriptCreateRequest,
    ScriptDetail,
    ScriptListResponse,
    ScriptPublishRequest,
    ScriptSummary,
)
from app.controllers.auth_deps import Principal, require_role
from app.domain.game.media import AssetKind
from app.infrastructure.errx import codes, new
from app.infrastructure.models.script import Script as ScriptRecord
from app.services.progress_hub import GenerationProgressHub
from app.services.script_library import ScriptLibrary
from app.services.script_projection import script_summary

router = APIRouter(prefix="/api", tags=["scripts"])

# 教师上传图片上限（#49）：生图 provider 常见输出在 4MB 内，上传放宽到 8MB。
_MAX_UPLOAD_BYTES = 8 * 1024 * 1024
# 允许的图片 MIME（转码侧 Pillow 支持 png/jpeg/webp 输入）。
_ALLOWED_IMAGE_TYPES = ("image/png", "image/jpeg", "image/webp")


def get_script_library() -> ScriptLibrary:
    """进程级 ScriptLibrary（由组合根 `app.composition` 装配）。"""
    return get_container().script_library


_Teacher = Annotated[Principal, Depends(require_role(UserRole.TEACHER))]
_Viewer = Annotated[
    Principal,
    Depends(require_role(UserRole.SUPER_ADMIN, UserRole.TEACHER, UserRole.STUDENT)),
]


async def _detail(library: ScriptLibrary, row: ScriptRecord, actor) -> ScriptDetail:
    package = ScriptPackage.model_validate(row.script_data) if row.script_data else None
    # 生成进度仅对 owner 可见（含失败详情）；他人读取已发布剧本时不暴露
    is_owner = row.owner_user_id == actor.user_id
    generation = await library.progress(row.id) if is_owner else None
    review = await library.review(row.id) if is_owner else None
    return ScriptDetail(
        script=script_summary(row),
        package=package,
        generation=generation,
        review=review,
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
    return script_summary(row)


@router.get("/scripts", response_model=ScriptListResponse)
async def list_scripts(
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptListResponse:
    """教师剧本库：当前教师自有的全部剧本（含草稿）。"""
    rows = await library.list_scripts(principal.actor)
    return ScriptListResponse(items=[script_summary(r) for r in rows])


# 注意：必须定义在 `/scripts/{script_id}` 之前，避免 "square" 被当作 script_id 匹配。
@router.get("/scripts/square", response_model=ScriptListResponse)
async def square_scripts(
    principal: _Viewer,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptListResponse:
    """剧本广场（#21）：已发布且对当前用户可见（同 org 或 public）的剧本。"""
    rows = await library.list_visible(principal.actor)
    return ScriptListResponse(items=[script_summary(r) for r in rows])


@router.get("/scripts/{script_id}", response_model=ScriptDetail)
async def get_script(
    script_id: int,
    principal: _Viewer,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptDetail:
    """剧本详情：owner 全量；他人仅已发布（org 同 org / public 跨 org）。"""
    row = await library.get_script(script_id, principal.actor)
    return await _detail(library, row, principal.actor)


@router.post("/scripts/{script_id}/generate", status_code=202, response_model=ScriptDetail)
async def generate_script(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptDetail:
    """启动异步生成（进程内任务 + 内存进度）；前端轮询详情。"""
    row = await library.start_generation(script_id, principal.actor)
    return await _detail(library, row, principal.actor)


@router.post(
    "/scripts/{script_id}/generation/resume",
    status_code=202,
    response_model=ScriptDetail,
)
async def resume_script_generation(
    script_id: int,
    body: GenerationResumeRequest,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptDetail:
    """教师闸门恢复（#34）：审阅后从断点继续，指令/编辑/终审动作注入 workflow。"""
    row = await library.resume_generation(script_id, principal.actor, resume=body)
    return await _detail(library, row, principal.actor)


@router.post(
    "/scripts/{script_id}/generation/cancel", status_code=202, response_model=ScriptDetail
)
async def cancel_script_generation(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptDetail:
    """教师停止运行中的生成（教师端可打断）：取消进程内任务并回写失败终态。"""
    row = await library.cancel_generation(script_id, principal.actor)
    return await _detail(library, row, principal.actor)


@router.get("/scripts/{script_id}/generation/stream")
async def stream_script_generation(
    script_id: int,
    request: Request,
    principal: _Viewer,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> StreamingResponse:
    """生成进度 SSE 流：实时增强通道，权威终态仍在 attempt 落库面（GET 详情）。

    - 订阅即先推一帧当前快照，避免空窗，之后每次落库都广播；
    - 仅 owner 持续收取（生成进度按归属可见，与详情同语义）；终态
      （succeeded/failed/awaiting_review 暂停）推完即收流，客户端无需断开；
    - 客户端断开（可打断按钮、离开页面）即注销。
    """
    row = await library.get_script(script_id, principal.actor)
    if row.owner_user_id != principal.actor.user_id:
        raise new(codes.AUTH_FORBIDDEN, extra={"reason": "not script owner"})

    async def event_source() -> AsyncGenerator[str, None]:
        with library.progress_hub.subscribe(script_id) as queue:
            snapshot = await library.progress(script_id)
            if snapshot is not None:
                yield f"data: {snapshot.model_dump_json()}\n\n"
            while True:
                if await request.is_disconnected():
                    return
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    # 心跳帧：SSE 注释行，防中间代理断空闲连接
                    yield ": keepalive\n\n"
                    continue
                yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                if payload.get("status") in GenerationProgressHub.FINAL_STATUSES:
                    return

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/scripts/{script_id}/assets/upload",
    status_code=201,
    response_model=AssetRef,
)
async def upload_script_asset(
    script_id: int,
    subject_key: Annotated[str, Form()],
    kind: Annotated[str, Form()],
    image: Annotated[UploadFile, File()],
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> AssetRef:
    """教师自有素材上传（#49）：先落库 READY，resume 时经 bind_upload 绑定槽位。

    仅草稿可传（发布即冻结，与剧本编辑同一冻结语义）；大小上限 8MB、仅常见
    图片类型——multipart 表单进不了 Pydantic 模型，边界校验在此处做，错误统一
    走 errx 信封（`error_response` 是 REST 错误唯一出口）。
    """
    _bad = codes.INP_INVALID_MEDIA_INPUT
    try:
        validate_subject_key(subject_key)
    except ValueError as exc:
        raise new(_bad, extra={"reason": str(exc)}) from exc
    if kind not in AssetKind._value2member_map_:
        raise new(_bad, extra={"reason": f"bad kind: {kind!r}"})
    if image.content_type not in _ALLOWED_IMAGE_TYPES:
        raise new(_bad, extra={"reason": f"unsupported type: {image.content_type}"})
    data = await image.read()
    if len(data) > _MAX_UPLOAD_BYTES:
        raise new(
            codes.MEDIA_UPLOAD_TOO_LARGE, extra={"size": len(data), "limit": _MAX_UPLOAD_BYTES}
        )
    return await library.upload_asset(
        script_id,
        principal.actor,
        subject_key=subject_key,
        kind=kind,
        image_bytes=data,
        content_type=image.content_type,
    )


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
    return await _detail(library, row, principal.actor)


@router.post("/scripts/{script_id}/publish", response_model=ScriptSummary)
async def publish_script(
    script_id: int,
    body: ScriptPublishRequest,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptSummary:
    """发布（org/public）；发布后核心内容不可编辑，仅可改可见性/下架。"""
    row = await library.publish(script_id, principal.actor, body.visibility)
    return script_summary(row)


@router.post("/scripts/{script_id}/unpublish", response_model=ScriptSummary)
async def unpublish_script(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> ScriptSummary:
    """下架：不再进库，存量世界可继续。"""
    row = await library.unpublish(script_id, principal.actor)
    return script_summary(row)


@router.delete("/scripts/{script_id}", status_code=204)
async def delete_script(
    script_id: int,
    principal: _Teacher,
    library: Annotated[ScriptLibrary, Depends(get_script_library)],
) -> None:
    """删除草稿（已发布/下架不可删）。"""
    await library.delete(script_id, principal.actor)


__all__ = ["router", "get_script_library"]
