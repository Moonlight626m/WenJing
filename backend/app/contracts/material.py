"""材料与证据契约：MaterialInput / Material / EvidenceRef。

- MaterialInput 是用户的原始输入（粘贴或上传），导入时校验并规范化。
- EvidenceRef 区分原文证据（字符区间/段落引用）与网络补充来源；
  原文对 Stage 2 的人物、关系、关键事件与顺序具有权威性（spec 决策）。
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, HttpUrl

from app.contracts.base import ContractModel, VersionedContract


class MaterialSource(StrEnum):
    """材料来源：粘贴文本或上传文件。"""

    PASTE = "paste"
    UPLOAD = "upload"


class MaterialInput(VersionedContract):
    """用户提交的课文原文输入（未经规范化）。"""

    source: MaterialSource
    filename: str | None = None
    raw_text: str = Field(min_length=1)


class Material(VersionedContract):
    """规范化后的课文材料：内容 hash 是去重与证据引用的锚点。"""

    content_hash: str = Field(description="SHA-256 hex of normalized text")
    normalized_text: str
    char_count: int = Field(ge=1)
    created_at: datetime | None = None


class EvidenceSourceType(StrEnum):
    """证据来源类型：原文 / 推断 / 网络补充。"""

    ORIGINAL_TEXT = "original_text"
    INFERENCE = "inference"
    WEB = "web"


class ConfidenceLevel(StrEnum):
    """论断可信度分级：素材考证与 doubter 审核共用（spec 裁决）。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class OriginalEvidence(VersionedContract):
    """原文证据：以原文字符区间或段落标识定位。"""

    source_type: Literal["original_text"] = EvidenceSourceType.ORIGINAL_TEXT.value
    excerpt: str = Field(min_length=1)
    paragraph_index: int | None = Field(default=None, ge=0)
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


class WebEvidence(VersionedContract):
    """网络补充证据：记录来源、URL、抓取时间与内容 hash，供审计。"""

    source_type: Literal["web"] = EvidenceSourceType.WEB.value
    url: HttpUrl
    title: str
    fetched_at: datetime
    content_hash: str
    excerpt: str


# 证据引用联合：按 source_type 判别；列表/单值处均可直接使用。
EvidenceRef = Annotated[
    OriginalEvidence | WebEvidence,
    Field(discriminator="source_type"),
]


class ClaimRef(ContractModel):
    """单条论断的溯源登记（素材集 claims 集中登记表，spec 裁决）。

    - target：论断在产物中的定位（字段路径或论断短语）；
    - source_type + confidence 是「来源 × 可信度」两维标注；
    - evidence_ref 指向支持该论断的原文区间或网络来源（推断类可为原文依据）。
    """

    target: str = Field(min_length=1)
    source_type: EvidenceSourceType
    confidence: ConfidenceLevel
    evidence_ref: EvidenceRef | None = None
    note: str = ""


class SourceConflict(ContractModel):
    """外部资料与课文的冲突记录：素材收集时显式登记，以原文为准。"""

    claim: str = Field(min_length=1)
    original_evidence: str = Field(min_length=1)
    external_source: str = Field(min_length=1)
    resolution: str = Field(min_length=1)
