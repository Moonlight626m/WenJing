"""事件/情景划分节点 prompt v2（prompt 落库：段落经 PromptBundle 取值）。

段落构成（section）：
- system：角色定位与忠实性总纲；
- scene_rules：场景划分判据（价值转折 / 切换点）；
- beat_rules：节拍粒度判据（行为/反应交换）；
- interaction_rules：介入点写法（drama manager 心智，为运行时留白）；
- checklist：输出前自检。

输出契约文本与 Pydantic 契约同步，留在代码不落库。
"""

from __future__ import annotations

from app.contracts.content import TextAnalysis
from app.domain.prompts.bundle import PromptBundle, default_bundle

NODE = "divide_events"
STAGE = "script_gen"
VERSION = "v2"
PROMPT_VERSION = f"{NODE}.{VERSION}"

SYSTEM = """\
你是剧本结构设计师，专长把叙事文本改编为可排演的课堂情景剧结构。
依据课文原文的关键事件顺序与素材集，把课文划分为可直接推进的\
情景（场景）与事件节拍（beat）。

忠实性总纲：划分必须忠实原文进程——关键 beat 的先后顺序不得违背\
原文关键事件顺序，不得增删关键事件、不得改变原文结局；\
压缩与取舍只允许发生在非关键细节上。\
"""

SCENE_RULES = """\
【场景划分判据】
- 每个场景必须承载一次可感知的价值转折：人物处境/关系/认知发生 A→B 的变化；\
没有独立转折的段落并入上一场景，不要为凑场次拆分；
- 场景切换点 = 原文中的时空跳转或人物进出（新地点、新的人物组合、时间推移）；
- 每场聚焦一个戏剧性问题（能被"是/否"式回答检验的悬念）；
- 全剧场景数 3-5 个为宜，篇幅均衡（不应出现远超其他场景的巨型场景）；
- 场景必须覆盖全部关键事件，且关键事件在场景间的相对顺序与原文一致。
"""

BEAT_RULES = """\
【节拍粒度判据】
- 一个 beat = 一次完整的行为/反应交换：谁做了什么、引出谁的什么反应；\
纯氛围描写不足以独立成拍；
- 每场 3-6 个 beat；一个 beat 不得跨越场景边界；
- 关键 beat（is_key_event=true）精确对应原文关键事件，key_event_order \
严格递增、必须指向【关键事件】中真实存在的序号；
- 非关键 beat 承担铺垫、过渡与细节丰满，但不得与原文冲突。
"""

INTERACTION_RULES = """\
【介入点（玩家参与空间）】
本剧本将进入角色扮演课堂：学生会扮演其中人物，由角色 agent 即时对戏。
- 每个场景在合适处给出 interaction_point：说明适合玩家扮演的人物、\
玩家在此刻可以做什么（有话可说/有事可做的时刻）；
- 关键事件发生前的介入不得改变事件本身：must_not_change 列出\
介入不得影响的关键事件序号；
- 旁白过场或无玩家在场的场景，interaction_point 置为 null；
- 介入点不是表演指令：只描述参与空间，不预设玩家台词。
"""

SELF_CHECK = """\
【输出前自检】
- 每个场景是否都有一次价值转折？每个 beat 是否都是完整的行为/反应交换？
- 关键事件是否全覆盖、顺序与原文一致、key_event_order 是否为合法整数？
- 参与人物名是否全部取自【人物列表】？
- 有玩家可参与的场景是否已给出介入点？
"""

DEFAULTS: dict[str, str] = {
    "system": SYSTEM,
    "scene_rules": SCENE_RULES,
    "beat_rules": BEAT_RULES,
    "interaction_rules": INTERACTION_RULES,
    "checklist": SELF_CHECK,
}

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
      ],
      "interaction_point": {
        "player_role_hint": "适合玩家扮演的人物名（字符串，可为空）",
        "what_player_can_do": "玩家在此刻可做的事（字符串）",
        "must_not_change": [介入不得影响的关键事件序号（整数数组，可为空）]
      } 或 null
    }
  ]
}"""


def build_user_message(
    analysis: TextAnalysis,
    dossier_json: str,
    *,
    directives: list[str] | None = None,
    bundle: PromptBundle | None = None,
) -> str:
    b = bundle if bundle is not None else default_bundle(STAGE, NODE, VERSION, DEFAULTS)
    lines = [
        f"[prompt_version={PROMPT_VERSION}]",
        b.text("system"),
        "",
        b.text("scene_rules"),
        "",
        b.text("beat_rules"),
        "",
        b.text("interaction_rules"),
        "",
        "【字段类型契约（必须严格遵守，只输出此 JSON）】",
        _OUTPUT_CONTRACT,
        "【硬性约束】",
        "- key_event_order 是整数或 null，严禁写成 \"e1\" 等字符串；",
        "- is_key_event=true 的 beat 必须给出对应原文关键事件的 key_event_order；",
        "- 关键 beat 的先后顺序必须与【关键事件】顺序一致；",
        "- interaction_point 是对象或 null，严禁写成字符串；",
        "- 参与人物名只能取自【人物列表】。",
        "",
        b.text("checklist"),
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
