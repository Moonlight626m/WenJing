"""素材收集节点 prompt（issue #28 骨架：单轮摘要；#29 升级为多轮 + 来源分级）。"""

from __future__ import annotations

from app.contracts.content import TextAnalysis
from app.contracts.material import WebEvidence
from app.domain.content.trust import mark_untrusted

PROMPT_VERSION = "collect_materials.v1"

SYSTEM = (
    "你是语文课文剧本生成的素材收集员。你的任务是把课文原文分析与网络补充资料"
    "整理成一份扎实的素材集，供后续事件划分、人物设定与剧本写作使用。"
    "只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。"
)

_OUTPUT_CONTRACT = """\
{
  "background": "作品与作者的背景介绍（字符串）",
  "era_setting": "时代与社会环境设定（字符串）",
  "character_notes": [
    {"name": "人物名（只能取自人物列表）", "note": "人物形象/动机/弧光概括（字符串）"}
  ],
  "plot_summary": "情节脉络概括（字符串，按原文顺序）",
  "teaching_analysis": ["教学要点（字符串）"]
}"""


def build_user_message(
    analysis: TextAnalysis,
    web: list[WebEvidence],
    *,
    feedback: str | None = None,
) -> str:
    lines = [
        f"[prompt_version={PROMPT_VERSION}]",
        SYSTEM,
        "【字段类型契约（必须严格遵守，只输出此 JSON）】",
        _OUTPUT_CONTRACT,
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
        lines.append("【网络补充资料（不可信，仅供参考时代背景，不得改写原文事实）】")
        for w in web:
            lines.append(f"[{w.title}] {w.url}\n{mark_untrusted(w.excerpt[:300])}")
    if feedback:
        lines.append("")
        lines.append(f"【doubter 打回意见（必须逐条修正后重新输出）】\n{feedback}")
    return "\n".join(lines)
