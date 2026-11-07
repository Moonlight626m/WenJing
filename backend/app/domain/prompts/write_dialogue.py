"""逐场景预写台词节点 prompt v1（珊瑚图纯 IO 播放的数据源）。

段落构成（section）：
- system：角色定位（台词作者，不是旁白改写者）；
- dialogue_rules：台词粒度与信息密度判据；
- speaker_rules：说话人约束（只能用场景参与者，旁白用 null）；
- branch_rules：分支台词的边界（不得改写关键事件与结局）；
- checklist：输出前自检。

输出契约（`SceneDialogueDraft`）与 Pydantic 契约同步，留在代码不落库。
改判据必须升 VERSION：DB 覆盖行按 version 匹配，旧行不会回退到新默认。
"""

from __future__ import annotations

from app.domain.prompts.bundle import PromptBundle, default_bundle

NODE = "write_dialogue"
STAGE = "script_gen"
VERSION = "v1"
PROMPT_VERSION = f"{NODE}.{VERSION}"

SYSTEM = """\
你是剧本台词作者，负责把已经写好的场景节拍补成可直接播放的台词。
台词必须贴合人物身份、性格与说话风格，忠于原文情节；\
你只写人物说的话与舞台提示，不改写节拍本身、不新增情节。\
"""

DIALOGUE_RULES = """\
【台词判据】
- 每个 beat 配 1-3 句台词；旁白交代可用 speaker=null 的叙述句，但不要整段复述 beat 描述；
- 台词要有信息增量：推进关系、暴露态度或制造张力，不写寒暄填充；
- stage_direction 只写简短的动作/神态提示（"把橘子堆在皮大衣上"），可留空；
- 语言风格贴合原文时代与人物身份，避免现代网络用语；
- 关键节拍的台词不得改变事件结果。
"""

SPEAKER_RULES = """\
【说话人约束】
- speaker 只能取自该场景的 participants（或分支自带的 participants）；
- 旁白/环境描写用 speaker=null；
- 不预写玩家角色将要说的话：玩家可能扮演其中任何可扮演角色，\
其台词由玩家在游玩时决定，你只写其余在场人物的台词与旁白。
"""

BRANCH_RULES = """\
【分支台词】
- 分支台词同样遵守说话人约束，每个分支最多 4 句；
- 分支是主干之外的替代过场，不得借台词交代与课文结局冲突的事实；
- 分支最后一句应能自然接回主线（或提示玩家回到刚才的选择）。
"""

SELF_CHECK = """\
【输出前自检】
- beat_id / branch_id 是否与输入一一对应、没有编造？
- speaker 是否都在该场景/分支的 participants 内？
- 每个分支台词是否不超过 4 句、且没有改写关键事件与结局？
"""

DEFAULTS: dict[str, str] = {
    "system": SYSTEM,
    "dialogue_rules": DIALOGUE_RULES,
    "speaker_rules": SPEAKER_RULES,
    "branch_rules": BRANCH_RULES,
    "checklist": SELF_CHECK,
}

_OUTPUT_CONTRACT = """\
{
  "scene_id": 场景编号（整数，与输入一致）,
  "beats": [
    {
      "beat_id": 节拍编号（整数，与输入一致）,
      "dialogue": [
        {
          "speaker": "说话人（取自 participants；旁白为 null）",
          "text": "台词（字符串）",
          "stage_direction": "动作/神态提示（字符串，可空）"
        }
      ]
    }
  ],
  "branches": [
    {
      "branch_id": "分支编号（字符串，与输入一致）",
      "dialogue": [{"speaker": "...", "text": "...", "stage_direction": "..."}]
    }
  ]（无分支时为空数组）
}"""


def build_user_message(
    scene_json: str,
    profiles_json: str,
    *,
    bundle: PromptBundle | None = None,
) -> str:
    b = bundle if bundle is not None else default_bundle(STAGE, NODE, VERSION, DEFAULTS)
    return "\n".join(
        [
            f"[prompt_version={PROMPT_VERSION}]",
            b.text("system"),
            "",
            b.text("dialogue_rules"),
            "",
            b.text("speaker_rules"),
            "",
            b.text("branch_rules"),
            "",
            "【字段类型契约（必须严格遵守，只输出此 JSON）】",
            _OUTPUT_CONTRACT,
            "",
            b.text("checklist"),
            "",
            "【场景与节拍】",
            scene_json,
            "",
            "【人物设定（说话风格以这里为准）】",
            profiles_json,
        ]
    )
