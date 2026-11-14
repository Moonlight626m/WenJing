"""beat 文本的展示切分：玩家可见叙述 vs 戏剧目标。

v3 剧本书写提示词把「事件骨架 + 戏剧目标」写进同一个 `beat.description`
（形如「……背影。目标：收束于泪光中的背影。」），播放器原样把它当旁白念给
玩家。v4 起目标在独立的 `Beat.goal` 字段；存量剧本包由这里一次性拆开：
description 只留玩家可见的叙述，目标并入 goal（新包 goal 非空时以新包为准）。

只在引擎侧拆：教师端剧本预览仍按原始存档显示，便于排查生成质量问题。
"""

from __future__ import annotations

import re

# 只匹配「目标：」这个 v3 模板标记；句中正常出现的「目标」不受影响。
_GOAL_MARKER = re.compile(r"(?:戏剧)?目标\s*[：:]")
_OPENERS = "（("
# 句末标点与收尾引号/括号：注记前必须是句子边界，避免误伤正常叙述
_CLOSERS = "。；;！？!?」』”’）)"


def split_goal_note(description: str, goal: str = "") -> tuple[str, str]:
    """返回 (玩家可见描述, 戏剧目标)。

    `goal` 已填（v4 包）时目标以包内值为准，但 description 里**仍会**剥掉残留的
    「目标：…」注记（模型偶发不遵守新契约，防御一次）。只有存量包才会把注记内容
    回填进返回值里的 goal。
    """
    match = _GOAL_MARKER.search(description)
    if match is None:
        return description, goal
    head = description[: match.start()].rstrip()
    if head and head[-1] not in _CLOSERS and head[-1] not in _OPENERS:
        # 句中的「目标：」不是作者注记（例如人物在说自己的目标），保持原样
        return description, goal
    if head and head[-1] in _OPENERS:
        head = head[:-1].rstrip()
    note = description[match.end() :].strip().rstrip("）)").strip()
    return head, goal or note
