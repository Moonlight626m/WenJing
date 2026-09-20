"""事件/情景划分节点 prompt（issue #28 骨架；#31 深化为独立节点 + 教师闸门）。"""

from __future__ import annotations

from app.contracts.content import TextAnalysis

PROMPT_VERSION = "divide_events.v1"

SYSTEM = (
    "你是剧本结构设计师。依据课文原文的关键事件顺序与素材集，把课文划分为"
    "可直接推进的情景（场景）与事件节拍（beat）。划分必须忠实原文进程："
    "关键 beat 的先后顺序不得违背原文关键事件顺序。"
    "只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。"
)

_OUTPUT_CONTRACT = """\
{
  "scenes": [
    {
      "title": "场景标题（字符串）",
      "participants": ["场景中出现的人物名（取自人物列表）"],
      "beats": [
        {
          "description": "该节拍发生的事件/推进（字符串）",
          "is_key_event": 布尔值,
          "key_event_order": 关键事件序号（整数，从 1 起；非关键事件为 null）
        }
      ]
    }
  ]
}"""


def build_user_message(
    analysis: TextAnalysis,
    dossier_json: str,
    *,
    directives: list[str] | None = None,
) -> str:
    lines = [
        f"[prompt_version={PROMPT_VERSION}]",
        SYSTEM,
        "【字段类型契约（必须严格遵守，只输出此 JSON）】",
        _OUTPUT_CONTRACT,
        "【硬性约束】",
        "- key_event_order 是整数或 null，严禁写成 \"e1\" 等字符串；",
        "- is_key_event=true 的 beat 必须给出对应原文关键事件的 key_event_order；",
        "- 关键 beat 的先后顺序必须与【关键事件】顺序一致；",
        "- 参与人物名只能取自【人物列表】。",
        "",
        "【人物列表】",
    ]
    for c in analysis.characters:
        traits = "、".join(filter(None, [c.role, c.personality])) or "（按原文理解）"
        lines.append(f"- {c.name}：{traits}")
    lines.append("【关键事件（按原文顺序）】")
    for ke in sorted(analysis.key_events, key=lambda k: k.order):
        lines.append(f"- 序号 {ke.order}：{ke.title}")
    lines.append("")
    lines.append("【素材集结论（供参考，事实以原文为准）】")
    lines.append(dossier_json)
    if directives:
        lines.append("")
        lines.append("【教师指导（必须遵守的额外约束）】")
        for d in directives:
            lines.append(f"- {d}")
    return "\n".join(lines)
