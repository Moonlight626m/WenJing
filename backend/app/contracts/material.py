"""材料输入与材料契约。

- `MaterialInput`：用户输入（粘贴或 `.txt`/`.md` 上传），契约层做基础规范化与大小约束；
  编码/扩展名/空内容等深度校验由 Content Pipeline Ingestion（ticket #9）负责。
- `Material`：导入后的课文材料（含内容 hash 与体裁判断结果），是后续生成的事实底座。
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MATERIAL_SCHEMA_VERSION = 1
MAX_MATERIAL_BYTES = 1_000_000  # 1 MiB，与 spec 输入限制一致


class GenreKind(StrEnum):
    """核心 MVP 支持的叙事类体裁；UNKNOWN = 尚未判断或不适配。"""

    NOVEL = "novel"
    NARRATIVE_PROSE = "narrative_prose"
    DRAMA = "drama"
    CHARACTER_STORY = "character_story"
    UNKNOWN = "unknown"


class MaterialInput(BaseModel):
    """用户提供的原始输入。"""

    model_config = ConfigDict(extra="forbid")

    raw_text: str
    source_type: Literal["paste", "file"]
    filename: str | None = None
    schema_version: int = MATERIAL_SCHEMA_VERSION

    @field_validator("raw_text")
    @classmethod
    def _strip_text(cls, v: str) -> str:
        return v.strip()

    @field_validator("raw_text")
    @classmethod
    def _enforce_size(cls, v: str) -> str:
        if len(v.encode("utf-8")) > MAX_MATERIAL_BYTES:
            raise ValueError(f"material exceeds {MAX_MATERIAL_BYTES} bytes")
        return v

    @model_validator(mode="after")
    def _file_requires_filename(self) -> MaterialInput:
        if self.source_type == "file" and not self.filename:
            raise ValueError("file input requires filename")
        return self


class Material(BaseModel):
    """导入后的课文材料。"""

    model_config = ConfigDict(extra="forbid")

    material_id: UUID
    session_id: UUID
    raw_text: str
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    genre: GenreKind = GenreKind.UNKNOWN
    encoding: Literal["utf-8"] = "utf-8"
    filename: str | None = None
    created_at: datetime
    schema_version: int = MATERIAL_SCHEMA_VERSION


def hash_text(raw_text: str) -> str:
    """规范化文本的内容 hash（UTF-8 字节的 sha256）。"""
    return hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
