"""剧本库契约（issue #19 / ADR-0002 §3）：教师创作 API 的请求/投影 DTO。

- 素材与剧本独立归属 owner/org；草稿→发布→下架为显式生命周期。
- `script` 只在生成成功后出现在详情里；生成过程经 `generation` 轮询。
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import Field, field_validator

from app.contracts.base import VersionedContract
from app.contracts.enums import ScriptStatus, ScriptVisibility
from app.contracts.generation import GenerationProgress
from app.contracts.script import ScriptPackage


class MaterialPublic(VersionedContract):
    """素材对外投影（不含原文全文，避免大 payload）。"""

    id: int
    title: str | None = None
    content_hash: str
    char_count: int = Field(ge=1)
    created_at: datetime | None = None


class ScriptCreateRequest(VersionedContract):
    """从素材创建剧本草稿：name/description 为教师命名，内容待生成。"""

    material_id: int
    name: str = Field(min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def _reject_blank_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name must not be blank")
        return value


class ScriptPublishRequest(VersionedContract):
    """发布时选择可见性（默认 org）；公开剧本跨 org 可见。"""

    visibility: ScriptVisibility = ScriptVisibility.ORG


class GenerationResumeRequest(VersionedContract):
    """教师闸门恢复（#34）：指导指令随恢复注入下游节点（原样透传）。"""

    directives: list[str] = Field(default_factory=list)


class ScriptSummary(VersionedContract):
    """剧本列表项/发布结果的轻量投影。"""

    id: int
    name: str
    description: str | None = None
    status: ScriptStatus
    visibility: ScriptVisibility
    material_id: int | None = None
    owner_user_id: uuid.UUID
    org_id: uuid.UUID
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ScriptDetail(VersionedContract):
    """剧本详情：生成成功后带 `script`；生成中/失败时带 `generation`。"""

    script: ScriptSummary
    package: ScriptPackage | None = None
    generation: GenerationProgress | None = None


class ScriptListResponse(VersionedContract):
    """剧本列表（教师库 / 学生广场共用形状）。"""

    items: list[ScriptSummary] = Field(default_factory=list)


__all__ = [
    "MaterialPublic",
    "ScriptCreateRequest",
    "ScriptPublishRequest",
    "GenerationResumeRequest",
    "ScriptSummary",
    "ScriptDetail",
    "ScriptListResponse",
]
