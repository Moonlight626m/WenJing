"""角色发言文本的舞台提示拆分（运行期角色把动作写进括号）。

提示词要求「可在括号里补一句简短的动作或神态」，模型实际产出形如
`（把橘子堆在皮大衣上）这话我记着`。整句直接进字幕会让玩家分不清哪句是
说出口的、哪句是动作，所以落库前拆成 `text` + `stage_direction`：
台词只留说出口的部分，动作单独渲染。前端对在途流式文本有同一套拆分
（`frontend/src/lib/stage-direction.ts`）。
"""

from __future__ import annotations

import re

_LEADING = re.compile(r"^\s*[（(]([^（）()]{1,60})[）)]\s*")
_TRAILING = re.compile(r"\s*[（(]([^（）()]{1,60})[）)]\s*$")


def split_stage_direction(raw: str) -> tuple[str, str]:
    """返回 (台词, 舞台提示)。整句都是动作时原样返回、不拆。"""
    actions: list[str] = []
    rest = raw
    while match := _LEADING.match(rest):
        actions.append(match.group(1).strip())
        rest = rest[match.end() :]
    while match := _TRAILING.search(rest):
        actions.append(match.group(1).strip())
        rest = rest[: match.start()]
    text = rest.strip()
    if not text:
        return raw.strip(), ""
    return text, "；".join(action for action in actions if action)


__all__ = ["split_stage_direction"]
