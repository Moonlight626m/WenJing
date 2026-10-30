"""画师层（PromptWriter）：画面语转写 agent（方案 branch-montage-dm §5）。

SceneDesigner 付费生成路径里的 LLM 转写层：输入「节拍文本 + 视觉锚点 +
在场人物结构化外貌」，输出**画面主体描述**（不是最终 prompt）——画风段与
构图尾巴仍由 `build_generation_prompt` 确定性追加（预算/安全校验的单点）。

设计取舍：
- **不进 `domain/prompts/` 的 DB 覆盖体系**：与 image_review.py 同理，这是
  运行期媒体路径而非生成 workflow 节点，prompt 内联在代码里；若未来教师
  需要可调，再迁移 PromptManager（另立项）。
- **去重键不含画师层输出**：LLM 每次措辞不同，进键则缓存永不命中；
  同一确定性 description 的重跑/重绘直接复用。
- **失败降级**：画师层任何失败（LLM 异常/空输出/输出被安全过滤命中）都
  回退到确定性 description 拼装——完整性优先于画面质量，场景永远有图。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from pydantic import BaseModel, Field

from app.contracts.enums import UsagePurpose
from app.domain.game.media import AssetKind
from app.domain.generation.json_text import extract_json
from app.domain.llm import LLMService

logger = logging.getLogger("wenjing.game.prompt_writer")

# 转写产物版本：由组合根并入 SceneDesigner.provider_version——改 prompt 必须
# bump，否则同描述命中旧图缓存。去重键主体仍是确定性 description（本模块
# 输出不进键，见模块 docstring）。
SCENE_PROMPT_VERSION = "scene_prompt.v1"

# 未交代降级词：appearance 的「原文未交代」/空字段按此渲染——绝不把
# 「原文未交代」四个字送 provider（对生图模型是噪声，对预算是浪费）。
_DEFAULT_FACE = "面容端正，符合人物身份"
_DEFAULT_HAIR = "符合时代与身份的常见发式"
_DEFAULT_CLOTHING = "符合时代与身份的常见衣着"
_DEFAULT_BUILD = "体态自然"


@runtime_checkable
class ScenePromptWriterPort(Protocol):
    """画师层端口：转写画面主体描述（SceneDesigner 注入；None = 回退现状拼装）。"""

    async def write(self, context: ScenePromptContext, *, max_chars: int) -> str: ...


@dataclass
class CharacterAppearance:
    """单个人物的外貌锚点集合（渲染为 prompt 片段）。"""

    name: str
    face: str = ""
    hair: str = ""
    clothing: str = ""
    accessories: str = ""
    build: str = ""

    def fragment(self) -> str:
        """渲染为一段画面语：已交代的原样用，未交代的降级为时代中性词。"""
        parts = [self.name]
        parts.append(f"面容{self.face if self.face else _DEFAULT_FACE}")
        parts.append(f"发型{self.hair if self.hair else _DEFAULT_HAIR}")
        parts.append(f"穿着{self.clothing if self.clothing else _DEFAULT_CLOTHING}")
        if self.accessories:
            parts.append(f"佩戴或持有{self.accessories}")
        parts.append(self.build if self.build else _DEFAULT_BUILD)
        return "，".join(parts)


@dataclass
class ScenePromptContext:
    """一场配图的转写输入：确定性 description 之外的结构化画面信息。"""

    title: str = ""
    beats: list[str] = field(default_factory=list)
    visual_notes: dict[str, str] = field(default_factory=dict)
    participants: list[CharacterAppearance] = field(default_factory=list)
    kind: AssetKind = AssetKind.SCENE_MONTAGE

    @property
    def era(self) -> str:
        return self.visual_notes.get("era", "")


class _WriterOutput(BaseModel):
    """画师层结构化输出：只写画面主体，不带画风段/尾巴（那是拼装器职责）。"""

    description: str = Field(min_length=1, max_length=1200)


class LLMPromptWriter:
    """LLM 实现：画面语转写。解析失败（含空输出）抛给调用方降级。"""

    def __init__(self, llm: LLMService) -> None:
        self._llm = llm

    async def write(self, context: ScenePromptContext, *, max_chars: int) -> str:
        raw = await self._llm.chat(
            [{"role": "user", "content": _build_user_message(context, max_chars)}],
            session_id="",  # 媒体路径不挂会话语义
            purpose=UsagePurpose.SCENE_PROMPT,
        )
        data = _WriterOutput.model_validate_json(extract_json(raw))
        description = data.description.strip()
        if not description:
            raise ValueError("画师层输出为空")
        return description


_KIND_HINT: dict = {
    "avatar": "1:1 半身头像，单人正面",
    "fullbody": "3:4 竖版全身立绘，单人直立",
    "background": "16:9 空镜环境，画面中不出现任何人物",
    "scene_montage": "16:9 横版完整场面：在场人物在环境中做出情节里的动作",
}


def _build_user_message(context: ScenePromptContext, max_chars: int) -> str:
    era = context.era or "符合课文设定的年代"
    lines = [
        f"[prompt_version={SCENE_PROMPT_VERSION}]",
        SYSTEM,
        "",
        COMPOSITION,
        "",
        ANCHOR_RULES,
        "",
        EXCLUSION_RULES,
        "",
        f"【输出规格】画面主体描述不超过 {max_chars} 个字符（不含画风段与构图尾巴）；"
        f"画幅：{_KIND_HINT.get(context.kind.value, _KIND_HINT['scene_montage'])}。",
        "",
        f"【时代基调】{era}",
    ]
    for key, label in (
        ("location", "地点"),
        ("time_of_day", "时段"),
        ("weather", "天气"),
        ("mood", "氛围"),
    ):
        value = context.visual_notes.get(key, "")
        if value:
            lines.append(f"【{label}】{value}")
    if context.title:
        lines.append(f"【场景】{context.title}")
    if context.beats:
        lines.append("【情节（按序发生）】")
        for beat in context.beats:
            lines.append(f"- {beat}")
    if context.participants:
        lines.append("【在场人物（外貌锚点，必须逐字采用）】")
        for p in context.participants:
            lines.append(f"- {p.fragment()}")
    lines.append("")
    lines.append(
        '【输出契约】只输出此 JSON：{"description": '
        '"画面主体描述（一段连贯中文，不含画风段与构图尾巴）"}'
    )
    return "\n".join(lines)


SYSTEM = """\
你是语文课文插图的画师转写助手。把给定的节拍文本、环境信息与人物外貌锚点，\
转写成一段可交给文生图模型的画面主体描述。

忠实性总纲：只做视觉转写，不新增事实——上文没有出现的动作、道具、表情一律不画；\
外貌锚点是硬约束：人物的脸、发型、服装、配饰、体格必须逐字采用给定的描述，\
这是同一角色跨图一致性的唯一来源。\
"""

COMPOSITION = """\
【构图要求】
- 写清画面里有什么：环境（建筑/器物/光线）、人物（谁在做什么）、位置关系；\
一段连贯的中文描述，不是关键字罗列；
- 完整场面图：人物置于画面中，动作按【情节】呈现，环境作背景层次；
- 头像：只画单人正面半身，神情按人物身份给中性沉着的面容；
- 全身立绘：单人直立全身像，可带外貌锚点或情节里的标志性动作；
- 空镜环境图：不出现任何人物，只写环境与氛围。

【笔调】课堂展示用插图，克制、写实、光线柔和自然；\
避免夸张变形、戏剧化强光与影视海报感。\
"""

ANCHOR_RULES = """\
【外貌锚点纪律】
- 在场人物的描述**必须**采用给定锚点，禁止自行补写或替换；\
锚点留白的字段一律以「符合时代与身份的常见形象」表达；
- 多人在场时，每人的外貌锚点逐个写入画面描述，位置关系用方位词交代\
（如「父亲在前，儿子在后」），画中人数与在场人物一致。\
"""

EXCLUSION_RULES = """\
【排除面（正向语义）】
- 画面保持教学插图的克制：构图干净、细节真实、无夸张光效；
- 不模仿职业摄影：不写镜头术语（特写/俯拍/景深）；
- 原文未交代且无法从时代推断的画面要素，宁可略过不画\
（缺失比想象更接近课文；不要为完整性补编细节）。\
"""


def render_appearance(appearance, name: str) -> CharacterAppearance:
    """契约/字典侧 appearance → CharacterAppearance（确定性渲染入口）。

    接受 dict 或带同名属性的模型（contracts.Appearance / domain 侧 dataclass），
    让运行期两侧都能走同一片段渲染。
    """
    if appearance is None:
        return CharacterAppearance(name=name)
    if isinstance(appearance, dict):
        return CharacterAppearance(
            name=name,
            face=appearance.get("face", ""),
            hair=appearance.get("hair", ""),
            clothing=appearance.get("clothing", ""),
            accessories=appearance.get("accessories", ""),
            build=appearance.get("build", ""),
        )
    return CharacterAppearance(
        name=name,
        face=getattr(appearance, "face", ""),
        hair=getattr(appearance, "hair", ""),
        clothing=getattr(appearance, "clothing", ""),
        accessories=getattr(appearance, "accessories", ""),
        build=getattr(appearance, "build", ""),
    )
