"""命令的人读动词与存档点标签词表。

会话层（写快照标签）和投影层（把标签替换成动作文本）共用，改词表只改这一处，
避免两处各写一份、改一处另一处静默失效。
"""

from __future__ import annotations

from app.contracts.enums import CommandKind

COMMAND_LABELS: dict[CommandKind, str] = {
    CommandKind.SELECT_ROLE: "选角",
    CommandKind.CHOOSE_OPTION: "选择",
    CommandKind.FREE_INPUT: "行动",
    CommandKind.SWITCH_SCENE: "换景",
    CommandKind.INTERVENE: "干涉世界",
    CommandKind.ENTER_STAGE3: "进入续写",
    CommandKind.CONFIRM_ENDING: "收束",
    CommandKind.EXIT_GAME: "退出",
    CommandKind.ROLLBACK_TO_EVENT: "回溯",
}

#: 投影时用玩家动作文本替换「动词 · 场景」的命令（这些命令的标签才有区分度）。
ACTION_COMMAND_LABELS = frozenset({"选择", "行动", "换景", "干涉世界"})

__all__ = ["ACTION_COMMAND_LABELS", "COMMAND_LABELS"]
