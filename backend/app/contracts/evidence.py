"""原文/网络证据引用模型。

- `OriginalEvidenceRef`：课文原文证据 —— Stage 2 的事实唯一权威来源（source_type="original"）。
- `WebEvidenceRef`：开放网络补充证据 —— 仅作背景/教学信息，不能覆盖原文关键事实。
- `EvidenceRef`：按 `source_type` 判别的联合类型。

每条证据必须带 excerpt（实际引用片段）；web 证据另记 url/title/retrieved_at/content_hash，
满足设计文档 §2.3 的溯源要求。
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

EVIDENCE_SCHEMA_VERSION = 1


class EvidenceRef(BaseModel):
    """证据基类：按 source_type 判别。"""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = EVIDENCE_SCHEMA_VERSION


class OriginalEvidenceRef(EvidenceRef):
    """课文原文证据：段落标识或字符区间 + 引用片段。"""

    source_type: Literal["original"] = "original"
    excerpt: str = Field(min_length=1)
    paragraph_id: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class WebEvidenceRef(EvidenceRef):
    """网络补充证据：可溯源的外部信息。"""

    source_type: Literal["web"] = "web"
    url: AnyHttpUrl
    title: str
    retrieved_at: datetime
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    excerpt: str = Field(min_length=1)


EvidenceRef = Annotated[
    OriginalEvidenceRef | WebEvidenceRef,
    Field(discriminator="source_type"),
]
