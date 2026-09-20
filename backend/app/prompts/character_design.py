"""人物设定节点 prompt（issue #28 骨架：每主要人物一个 agent 并行；#32 深化）。"""

from __future__ import annotations

PROMPT_VERSION = "character_design.v1"

SYSTEM = (
    "你是语文课文剧本的人物设定师。针对一个指定人物，依据原文与素材集"
    "产出可直接驱动角色 Agent 的设定。设定必须忠于原文：性格与背景"
    "只能来自原文可推断的内容，不得编造原文外的经历。"
    "只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释文字。"
)

_OUTPUT_CONTRACT = """\
{
  "public_background": "人物背景（字符串）",
  "personality_traits": ["性格标签（字符串数组，2-4 个）"],
  "speech_style": "说话风格（字符串或 null）",
  "is_player_playable": 布尔值（是否适合作为玩家扮演角色）
}"""


def build_user_message(
    *,
    name: str,
    original_traits: str,
    dossier_json: str,
    role_hint: str = "",
) -> str:
    return "\n".join(
        [
            f"[prompt_version={PROMPT_VERSION}]",
            SYSTEM,
            "【字段类型契约（必须严格遵守，只输出此 JSON）】",
            _OUTPUT_CONTRACT,
            "【目标人物】",
            f"姓名：{name}",
            f"原文线索：{original_traits or '（按原文理解）'}",
            f"在原文中的地位：{role_hint or '（未标注）'}",
            "",
            "【素材集结论（供参考，事实以原文为准）】",
            dossier_json,
        ]
    )
