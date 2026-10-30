"""教师闸门审阅契约（issue #34）：中间产物契约化 + 审阅/编辑请求模型。

- MaterialDossier / EventDivisionDraft 原是 workflow 内部类型，随 #34 中段
  与尾闸门落地契约化（教师编辑提交所需的请求模型必须引用同一形状）。
- GateReview：闸门暂停时展示给教师的中间产物快照（runner 捕获 interrupt
  载荷，经 script_generations.review 落库，教师端经 ScriptDetail.review 读取）。
- GateEdits：教师编辑语义（#34 裁决）——直接覆盖中间产物，不重新考证；
  未提供的字段视为未编辑。
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

from app.contracts.base import ContractModel, VersionedContract
from app.contracts.material import ClaimRef, SourceConflict, WebEvidence
from app.contracts.script import CharacterProfile, ScriptPackage

# 闸门位置：materials=素材收集后；pre_write=人物+场景划分后（write_script 前）；
# final=final_audit 总审通过后（终审，可打回重写）。
GateKind = Literal["materials", "pre_write", "final"]


class CharacterNote(ContractModel):
    """素材集里对单个人物的结论。"""

    name: str = Field(min_length=1)
    note: str = Field(min_length=1)


class MaterialDossier(ContractModel):
    """素材收集节点产物：考证过的背景/时代/人物/情节/教学结论。

    - 溯源不散落到每个字段：全部论断集中在 claims 登记表
      （来源 original_text/inference/web × 可信度 high/medium/low，spec 裁决）；
    - conflicts 登记外部资料与课文的冲突（以原文为准）。
    """

    background: str = Field(min_length=1)
    era_setting: str = Field(min_length=1)
    character_notes: list[CharacterNote] = Field(default_factory=list)
    plot_summary: str = Field(min_length=1)
    teaching_analysis: list[str] = Field(default_factory=list)
    claims: list[ClaimRef] = Field(default_factory=list)
    conflicts: list[SourceConflict] = Field(default_factory=list)


class InteractionPoint(ContractModel):
    """场景末尾的玩家介入点（drama manager 心智，spec 裁决）。

    为角色扮演运行时预留玩家介入空间：关键事件不可被介入改变，
    介入只发生在 must_not_change 之外的节拍间隙。
    """

    player_role_hint: str = ""
    what_player_can_do: str = Field(min_length=1)
    must_not_change: list[int] = Field(default_factory=list)


class BeatDraft(ContractModel):
    """划分草稿的单个节拍：key_event_order 指向原文关键事件序号。"""

    description: str = Field(min_length=1)
    is_key_event: bool = False
    key_event_order: int | None = Field(default=None, ge=1)


class SceneDraft(ContractModel):
    """划分草稿的单个场景。interaction_point 可空（无玩家在场/纯过场）。"""

    title: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    beats: list[BeatDraft] = Field(min_length=1)
    interaction_point: InteractionPoint | None = None


class EventDivisionDraft(ContractModel):
    """事件/情景划分草稿：beats 结构先于剧本书写（#31 深化）。"""

    scenes: list[SceneDraft] = Field(min_length=1)


class GateReview(VersionedContract):
    """闸门暂停时给教师看的中间产物快照（按 gate 字段决定哪些字段有意义）。

    终审闸门（#48 选项 A）随 `package` 天然携带场景/人物槽位上的 AssetRef，
    教师配图审批（#49）直接基于槽位状态发起 asset_ops，无需独立资产清单字段。
    """

    gate: GateKind
    dossier: MaterialDossier | None = None
    evidence: list[WebEvidence] = Field(default_factory=list)
    division: EventDivisionDraft | None = None
    profiles: list[CharacterProfile] = Field(default_factory=list)
    package: ScriptPackage | None = None


class AssetOp(VersionedContract):
    """教师对单个配图槽位的操作（#49）：随 resume 经 final_gate 生效。

    - `subject_key`：配图主体键（#48 命名）——`scene:{scene_id}` /
      `character:{name}`，与 AssetRef 所在槽位一一对应；
    - `asset_id`：仅 `bind_upload` 用（上传端点先落库、resume 再绑定）；
      其余操作按 subject_key 定位槽位，忽略该字段。

    生效语义（节点侧实现）：
    - `remove`：清空槽位 AssetRef（资产行留存；ADR-0005 明确删除/回收暂不立项）；
    - `regenerate`：重新配图（绕开该主体的既有资产缓存与同字节检索候选）；
    - `search_replace`：仅开放版权检索替换（不走付费生成；失败保留旧图）；
    - `bind_upload`：绑定教师上传的资产（upload 端点产出）。
    """

    op: Literal["remove", "regenerate", "search_replace", "bind_upload"]
    subject_key: str = Field(min_length=1)
    kind: Literal["background", "avatar", "fullbody"]
    asset_id: uuid.UUID | None = None


def validate_subject_key(subject_key: str) -> str:
    """上传端点的 subject_key 输入校验（#49）：`scene:{int}` / `character:{name}`。

    契约层没有对 AssetOp.subject_key 加 pattern——workflow 内部键是可信的，
    校验只需卡在系统边界（multipart 表单进不了 Pydantic 模型）。
    """
    if subject_key.startswith("scene:"):
        rest = subject_key.split(":", 1)[1]
        if rest.isdigit() and int(rest) >= 1:
            return subject_key
    elif subject_key.startswith("character:") and len(subject_key) > len("character:"):
        return subject_key
    raise ValueError(f"bad subject_key: {subject_key!r}")


class GateEdits(VersionedContract):
    """教师编辑载荷：教师改后的中间产物整体替换对应通道（None=未编辑）。

    `asset_ops` 是配图槽位操作列表（#49）：按 subject_key 累计应用，同一
    subject 多条时**后一条覆盖前一条**的意图（前端每次提交该槽位的最终意图）。
    """

    dossier: MaterialDossier | None = None
    division: EventDivisionDraft | None = None
    profiles: list[CharacterProfile] | None = None
    package: ScriptPackage | None = None
    asset_ops: list[AssetOp] = Field(default_factory=list)


__all__ = [
    "GateKind",
    "GateReview",
    "GateEdits",
    "AssetOp",
    "validate_subject_key",
    "CharacterNote",
    "MaterialDossier",
    "InteractionPoint",
    "BeatDraft",
    "SceneDraft",
    "EventDivisionDraft",
]
