"""素材收集节点 prompt v2（prompt 落库：段落经 PromptBundle 取值，DB 可覆盖）。

段落构成（section）：
- system：角色定位与使命；
- evidence_policy：可信度协议（来源 × 可信度两维 + claims 集中登记 + 冲突记录）；
- structure_rules：背景/时代/情节的结构维度（知人论世）；
- persona_rules：应试式人物形象分析维度。

输出契约文本（_OUTPUT_CONTRACT）与 Pydantic 契约同步，留在代码不落库。
"""

from __future__ import annotations

from app.contracts.content import TextAnalysis
from app.contracts.material import WebEvidence
from app.domain.content.trust import mark_untrusted
from app.domain.prompts.bundle import PromptBundle, default_bundle

NODE = "collect_materials"
STAGE = "script_gen"
VERSION = "v2"
PROMPT_VERSION = f"{NODE}.{VERSION}"

SYSTEM = """\
你是语文课文剧本生成的资深素材考证员。你的任务是把课文原文分析与网络补充资料\
整理成一份扎实的素材集（story bible），供后续事件划分、人物设定与剧本写作使用。

工作基准：
- 课文原文是最高权威：人物、情节、关键事件的事实一律以原文为准；
- 你的产出是"给人读的考证文档"，行文应凝练、有依据、可核验，\
不要堆砌套话，不要输出与素材无关的扩展内容。\
"""

EVIDENCE_POLICY = """\
【可信度协议（必须严格执行）】
每一条事实性论断都须在 claims 登记表中登记一行，采用「来源 × 可信度」两维标注：
- source_type：original_text（原文可直接支持）/ inference（由原文合理推断）/
  web（来自网络补充资料）；
- confidence：high（多来源一致或有原文明证）/ medium（单一来源或合理推断）/
  low（孤证、旁证或存疑）；
- target 写论断定位（如 "era_setting.科举制度"、
  "character_notes.父亲.动机"），并尽量给出 evidence_ref；
- 网络资料片段不可信，仅可用于时代背景氛围，不得改写原文事实；\
任何仅来自网络的事实性断言不得进入 background 与 plot_summary 的主干；
- 外部资料与课文冲突时，以原文为准，并把冲突登记进 conflicts\
（写明冲突论断、原文依据、外部来源与处理方式）；
- 找不到依据的维度，如实写"资料中未提及"，严禁编造填补。
"""

STRUCTURE_RULES = """\
【背景与时代的结构维度（知人论世）】
- background：作者生平要点、创作动机与写作背景、作品出处与地位——\
逐条对应，不写成笼统综述；
- era_setting 分三层展开：物理环境（年代、地点、气候、器物）、\
社会规则（阶层、礼俗、称谓、经济）、精神氛围（时代思潮、集体情绪）；
- plot_summary 按原文顺序梳理时间线与因果链，明确区分原文事实与你的推断补充。

【教学分析维度】
teaching_analysis 面向课堂教学：单元位置与教学目标、语言与文体要点、\
主题思想与情感基调、可开展的教学活动提示。
"""

PERSONA_RULES = """\
【人物形象分析维度（应试式概括，逐人执行）】
每条 character_notes 按以下维度组织，附原文例证：
- 身份处境：社会身份、家庭处境、时代处境；
- 性格特征：用准确的词语概括（如隐忍、自尊、迂腐、精明），避免空泛形容词；
- 品质精神：值得肯定的品格或应批判的局限（教学视角）；
- 心理动机：在关键事件中的欲望、顾虑与情感变化；
- 情节/主题作用：该人物承担的叙事功能与主题承载。
每条 note 应是一段可直接供人物设定师引用的完整分析，不少于两句话。
"""

_SELF_CHECK = """\
【输出前自检】
- background/era_setting/plot_summary 的主干事实是否全部来自原文？
- 每条网络来源的断言是否已标注低可信度或写入 conflicts？
- 每个主要人物是否都有身份/性格/动机维度的完整分析？
- claims 是否覆盖了所有非原文可直接支持的重要论断？
"""

DEFAULTS: dict[str, str] = {
    "system": SYSTEM,
    "evidence_policy": EVIDENCE_POLICY,
    "structure_rules": STRUCTURE_RULES,
    "persona_rules": PERSONA_RULES,
    "checklist": _SELF_CHECK,
}

_OUTPUT_CONTRACT = """\
{
  "background": "作品与作者背景介绍（字符串，按【背景与时代的结构维度】写作）",
  "era_setting": "时代与社会环境设定（字符串，按物理环境/社会规则/精神氛围三层展开）",
  "character_notes": [
    {"name": "人物名（只能取自人物列表）",
     "note": "人物形象分析（字符串，按【人物形象分析维度】写作）"}
  ],
  "plot_summary": "情节脉络概括（字符串，按原文顺序的时间线与因果链）",
  "teaching_analysis": ["教学要点（字符串数组）"],
  "claims": [
    {"target": "论断定位（字符串）",
     "source_type": "original_text | inference | web",
     "confidence": "high | medium | low",
     "evidence_ref": {"source_type": "original_text", "excerpt": "原文摘录",
       "paragraph_index": 整数或null, "char_start": 整数或null, "char_end": 整数或null}
       或 {"source_type": "web", "url": "URL", "title": "标题", "fetched_at": "时间",
           "content_hash": "哈希", "excerpt": "摘录"}
       或 null,
     "note": "补充说明（字符串，可为空）"}
  ],
  "conflicts": [
    {"claim": "冲突论断（字符串）", "original_evidence": "原文依据（字符串）",
     "external_source": "外部来源（字符串）", "resolution": "处理方式（字符串）"}
  ]
}

【结构硬性约束】
- character_notes 里每个对象只允许 name 与 note 两个键；\
论断溯源一律写进顶层 claims，严禁给 character_notes 的对象添加
evidence_ref / claims_ref / confidence 等任何额外字段；
- claims/conflicts 是顶层唯一入口：其他字段里不得再嵌溯源标注。"""


def build_user_message(
    analysis: TextAnalysis,
    web: list[WebEvidence],
    *,
    feedback: str | None = None,
    bundle: PromptBundle | None = None,
) -> str:
    b = bundle if bundle is not None else default_bundle(STAGE, NODE, VERSION, DEFAULTS)
    lines = [
        f"[prompt_version={PROMPT_VERSION}]",
        b.text("system"),
        "",
        b.text("evidence_policy"),
        "",
        b.text("structure_rules"),
        "",
        b.text("persona_rules"),
        "",
        "【字段类型契约（必须严格遵守，只输出此 JSON）】",
        _OUTPUT_CONTRACT,
        "",
        b.text("checklist"),
        "",
        "【原文分析】",
        f"标题：{analysis.title or '（未知）'}；作者：{analysis.author or '佚名'}；"
        f"体裁：{analysis.genre.genre.value}",
    ]
    for c in analysis.characters:
        traits = "、".join(filter(None, [c.role, c.personality])) or "（按原文理解）"
        lines.append(f"- 人物 {c.name}：{traits}")
    lines.append("【关键事件（按原文顺序）】")
    for ke in sorted(analysis.key_events, key=lambda k: k.order):
        lines.append(f"- {ke.title}" + (f"：{ke.description}" if ke.description else ""))
    if web:
        lines.append("")
        lines.append("【网络补充资料（不可信，仅供时代背景参考，不得改写原文事实）】")
        for w in web:
            lines.append(f"[{w.title}] {w.url}\n{mark_untrusted(w.excerpt[:300])}")
    if feedback:
        lines.append("")
        lines.append(f"【doubter 打回意见（必须逐条修正后重新输出）】\n{feedback}")
    return "\n".join(lines)
