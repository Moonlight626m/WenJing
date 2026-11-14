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
from app.contracts.script import (
    CharacterProfile,
    DialogueLine,
    Ending,
    InteractionPoint,  # noqa: F401 - re-export（Scene 亦引用）
    SceneOption,
    ScriptPackage,
    VisualNotes,
)

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


# InteractionPoint 定义在 contracts.script（Scene 也引用它）；这里经 import
# re-export 保持既有导入路径（`from app.contracts.review import InteractionPoint`）。
# Scene 引用 InteractionPoint 后它必须随剧本包一起被提升（伪分支挂接的前提）。

class BranchSpec(ContractModel):
    """划分草稿的分支规格（divide_events v3 产出，write_script 补写成 BranchScene）。

    只给规格不给成文：trigger_option 是该介入点的「典型玩家选择」一句话，
    不预设玩家必须这么说；value_turn 是分支内的 A→B 微转折（不得是主线
    关键转折，主线转折受 must_not_change 保护）。
    """

    branch_id: str = Field(pattern=r"^b[1-9][0-9]*$")
    trigger_option: str = Field(min_length=1)
    value_turn: str = Field(min_length=1)
    participants: list[str] = Field(default_factory=list)
    beat_outline: list[str] = Field(min_length=1)
    # 珊瑚图返回方式（divide_events v4）：choice 回决策点 / continue 续接主干；
    # ending_id 非空表示该分支是终局，不回主干。
    return_mode: Literal["choice", "continue"] = "continue"
    return_scene_id: int | None = None
    ending_id: str | None = None


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
    # 场景视觉锚点（文生图槽位：时代/地点/时段/天气/氛围，只写原文可推断）。
    visual_notes: VisualNotes | None = None
    # 伪分支规格（divide_events v3）：只在 interaction_point 非空的场景产出。
    branches: list[BranchSpec] = Field(default_factory=list)
    # 珊瑚图决策点（v4）：目标为 branch / 场景序号 / 结局；全空 = 续接主干。
    options: list[SceneOption] = Field(default_factory=list)


class EventDivisionDraft(ContractModel):
    """事件/情景划分草稿：beats 结构先于剧本书写（#31 深化）。"""

    scenes: list[SceneDraft] = Field(min_length=1)
    # 珊瑚图结局（v4）：空 = 旧式单一结局（stage2_ending_beat_id）。
    endings: list[Ending] = Field(default_factory=list)


class BeatDialogueDraft(ContractModel):
    """write_dialogue 节点的单节拍台词产出（按 beat_id 合并回剧本包）。"""

    beat_id: int
    dialogue: list[DialogueLine] = Field(default_factory=list)


class BranchDialogueDraft(ContractModel):
    """单分支台词产出（按 branch_id 合并）。"""

    branch_id: str = Field(min_length=1)
    dialogue: list[DialogueLine] = Field(default_factory=list)


class SceneDialogueDraft(ContractModel):
    """单场景台词产出：逐 beat 与逐分支各一组。"""

    scene_id: int
    beats: list[BeatDialogueDraft] = Field(default_factory=list)
    branches: list[BranchDialogueDraft] = Field(default_factory=list)


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
    kind: Literal["background", "avatar", "fullbody", "scene_montage"]
    asset_id: uuid.UUID | None = None


def validate_subject_key(subject_key: str) -> str:
    """上传端点的 subject_key 输入校验（#49）：`scene:{int}` / `character:{name}`。

    契约层没有对 AssetOp.subject_key 加 pattern——workflow 内部键是可信的，
    校验只需卡在系统边界（multipart 表单进不了 Pydantic 模型）。
    分支场景键 `scene:{int}::branch:{branch_id}`（伪分支的独立配图槽位，
    方案 branch-montage-dm §3）与主干键一样合法。
    """
    if subject_key.startswith("scene:"):
        rest = subject_key.split(":", 1)[1]
        if rest.isdigit() and int(rest) >= 1:
            return subject_key
        if "::" in rest:
            scene_part, _, branch_part = rest.partition("::")
            if (
                scene_part.isdigit()
                and int(scene_part) >= 1
                and branch_part.startswith("branch:")
                and len(branch_part) > len("branch:")
            ):
                return subject_key
    elif subject_key.startswith("character:") and len(subject_key) > len("character:"):
        return subject_key
    raise ValueError(f"bad subject_key: {subject_key!r}")


class GateEdits(VersionedContract):
    """教师编辑载荷：教师改后的中间产物整体替换对应通道（None=未编辑）。

    例外：`division.endings` 为空而原稿有结局时，工作流保留原稿结局——
    前端只编辑场景名/参与人物，空值视为回传丢字段（见
    `workflow/nodes.py::pre_write_gate`）。

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
    "BranchSpec",
    "BeatDraft",
    "SceneDraft",
    "EventDivisionDraft",
]
