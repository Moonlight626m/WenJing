"""人物设定节点 prompt v3（prompt 落库：段落经 PromptBundle 取值）。

段落构成（section）：
- system：角色定位与忠实性总纲；
- trait_rules：性格标签"标签 + 原文证据 + 行为化描述"写作法；
- speech_rules：说话风格五要素 + 示例台词；
- boundary_rules：知识边界与禁编造约束；
- playability_rules：is_player_playable 判断准则；
- appearance_rules：结构化外貌要素（文生图锚定，v3 新增）；
- checklist：输出前自检。

v3 变更（方案 branch-montage-dm）：新增 appearance 五字段——运行期 persona
无关但文生图必需；与 character-type 提示词一样执行「原文可推断、未交代
如实标注」纪律，外貌编造是教学方法性事故（课文插图是共同记忆）。

输出契约文本与 Pydantic 契约同步，留在代码不落库。
"""

from __future__ import annotations

from app.domain.prompts.bundle import PromptBundle, default_bundle

NODE = "character_design"
STAGE = "script_gen"
VERSION = "v3"
PROMPT_VERSION = f"{NODE}.{VERSION}"

SYSTEM = """\
你是语文课文剧本的人物设定师，为角色扮演课堂塑造可直接驱动角色 agent 的\
设定卡。针对一个指定人物，依据原文与素材集产出设定。

忠实性总纲：设定必须忠于原文——性格与背景只能来自原文可推断的内容，\
不得编造原文外的经历；素材集结论仅供深化理解，事实以原文为准。\
"""

TRAIT_RULES = """\
【性格标签写作法（show, don't tell）】
- 给出 2-4 个性格标签，每个标签必须配齐：
  evidence——支持该标签的原文例证（引原文细节或概括其行为）；
  behavior——行为化描述：这个性格在具体情境中如何表现（可观测的动作/习惯），\
运行时据此演绎，不要写抽象形容词的重复；
- 标签要准确且有区分度（如"隐忍自尊"优于"内向"）；\
禁止空泛标签（"好人""普通人"）与互相矛盾的标签堆叠。
"""

SPEECH_RULES = """\
【说话风格五要素（全部必填，未提及处写"原文未体现"）】
- era_layer：语言时代层——纯白话 / 浅文白夹杂 / 引用原文语汇（古文课文注意标定）；
- sentence_rhythm：句长与节奏——短促 / 绵长 / 爱用排比反问等；
- address_terms：称谓习惯——对长辈、平辈、晚辈各怎么称呼；
- catchphrases：口头禅与语气词——如"罢了""岂有此理""嗯……"；
- emotion_expression：情绪表达方式——直露 / 克制 / 冷嘲 / 先扬后抑等；
- 另给 2-3 句 sample_lines：该角色口吻的示例台词，须符合其身份与时代层，\
运行时以此校准语气。
"""

BOUNDARY_RULES = """\
【知识边界（防出戏）】
- 显式列出该角色知道的事（knows）：原文中他/她亲身经历、在场知晓的内容；
- 与不知道的事（not_knows）：原文时空之外的信息、其他人物未告知的隐情；
- 运行时遇到超纲问题，角色应以符合身份的方式回应（困惑、岔开、\
按原文价值观表态），而不是告知设定外信息。
- 背景只写原文可推断内容；原文未交代处写"原文未交代"，严禁补编经历。
"""

PLAYABILITY_RULES = """\
【是否适合玩家扮演（is_player_playable）】
适合玩家：戏份适中且贯穿全剧、动机清晰可共情、有主动选择空间、\
语言难度适中（中学生能自然模仿）；
适合 NPC（由角色 agent 扮演）：戏份碎片化或纯功能性、语言风格极端\
（如口音浓重、文言艰深）难以被学生自然模仿、或全剧出场极少的人物；
reason 用一句话写明判断依据。
"""

APPEARANCE_RULES = """\
【外貌五要素（appearance，文生图锚定）】
- 五字段全部给出：face（脸型/脸色/神情）、hair（发式发型）、\
clothing（服装，时代典型款式优先原文）、accessories（配饰与道具，\
只写原文点名的器物）、build（体格体态）；
- 只允许原文可推断内容：原文明示的外观（如课文点明的毡帽、项圈、圆脸）\
必须逐字保留；原文未交代处如实写"原文未交代"；
- 严禁为画面好看补写细节：具体五官、影视化造型、现代服饰一律不得出现；
- 配饰只写原文点名的器物——它常是人物命运的符号，多画亦错。
"""

SELF_CHECK = """\
【输出前自检】
- 每个性格标签是否都有原文证据与行为化描述？
- 说话风格五要素是否齐备、示例台词是否符合身份与时代层？
- 背景是否有编造原文外经历之处？
- 知识边界是否显式列出了"不知道"的内容？
- 外貌五要素是否有编造？未交代处是否如实标注？
"""

DEFAULTS: dict[str, str] = {
    "system": SYSTEM,
    "trait_rules": TRAIT_RULES,
    "speech_rules": SPEECH_RULES,
    "boundary_rules": BOUNDARY_RULES,
    "playability_rules": PLAYABILITY_RULES,
    "appearance_rules": APPEARANCE_RULES,
    "checklist": SELF_CHECK,
}

_OUTPUT_CONTRACT = """\
{
  "public_background": "人物背景（字符串，仅原文可推断内容）",
  "personality_traits": [
    {"label": "性格标签（字符串）", "evidence": "原文例证（字符串）",
     "behavior": "行为化描述（字符串）"}
  ],
  "speech_style": {
    "era_layer": "语言时代层（字符串）",
    "sentence_rhythm": "句长与节奏（字符串）",
    "address_terms": "称谓习惯（字符串）",
    "catchphrases": "口头禅与语气词（字符串）",
    "emotion_expression": "情绪表达方式（字符串）",
    "sample_lines": ["示例台词（字符串数组，2-3 句）"]
  } 或 null,
  "knowledge_boundary": {
    "knows": ["该角色知道的事（字符串数组）"],
    "not_knows": ["该角色不知道的事（字符串数组）"]
  },
  "is_player_playable": {"value": 布尔值, "reason": "判断理由（字符串）"},
  "appearance": {
    "face": "脸型/脸色/神情（字符串，未交代处写\"原文未交代\"）",
    "hair": "发式发型（字符串）",
    "clothing": "服装（字符串，时代典型款式）",
    "accessories": "配饰/道具（字符串，只写原文点名器物）",
    "build": "体格体态（字符串）"
  }
}

【JSON 纪律】字符串内部引用原文时，一律使用中文引号「」或''，\
禁止在字符串内出现未转义的英文双引号；输出必须是可被 json.loads 解析的合法 JSON。"""


def build_user_message(
    *,
    name: str,
    original_traits: str,
    dossier_json: str,
    role_hint: str = "",
    bundle: PromptBundle | None = None,
) -> str:
    b = bundle if bundle is not None else default_bundle(STAGE, NODE, VERSION, DEFAULTS)
    return "\n".join(
        [
            f"[prompt_version={PROMPT_VERSION}]",
            b.text("system"),
            "",
            b.text("trait_rules"),
            "",
            b.text("speech_rules"),
            "",
            b.text("boundary_rules"),
            "",
            b.text("playability_rules"),
            "",
            b.text("appearance_rules"),
            "",
            "【字段类型契约（必须严格遵守，只输出此 JSON）】",
            _OUTPUT_CONTRACT,
            "",
            b.text("checklist"),
            "",
            "【目标人物】",
            f"姓名：{name}",
            f"原文线索：{original_traits or '（按原文理解）'}",
            f"在原文中的地位：{role_hint or '（未标注）'}",
            "",
            "【素材集结论（供参考，事实以原文为准）】",
            dossier_json,
        ]
    )
