"""共享契约枚举：阶段、交互模式、命令类型、事件类型与错误域。

命令类型集合与每阶段 allowed_commands 是冻结契约的一部分（issue #2 验收标准 2）。
"""

from __future__ import annotations

from enum import StrEnum


class StageValue(StrEnum):
    """游戏顶层阶段的契约值（与 core.state_machine.GameStage 对齐）。"""

    INIT = "init"
    STAGE1_CREATING = "stage1_creating"
    STAGE1_COMPLETE = "stage1_complete"
    STAGE2_REENACTING = "stage2_reenacting"
    STAGE2_COMPLETE = "stage2_complete"
    STAGE3_EXTENDING = "stage3_extending"
    ENDED = "ended"


class InteractionMode(StrEnum):
    """交互设计器产出的三种输入模式（design_02 / spec 决策）。"""

    OPTIONS = "options"
    FREE_INPUT = "free_input"
    OPTIONS_WITH_FALLBACK = "options_with_fallback"


class CommandKind(StrEnum):
    """PlayerCommand 的类型集合：玩家唯一合法的游戏输入入口。"""

    SELECT_ROLE = "select_role"
    CHOOSE_OPTION = "choose_option"
    FREE_INPUT = "free_input"
    ROLLBACK_TO_EVENT = "rollback_to_event"
    ENTER_STAGE3 = "enter_stage3"
    CONFIRM_ENDING = "confirm_ending"
    EXIT_GAME = "exit_game"


# 每阶段允许的命令（allowed_commands 约束，runtime 校验依据）
ALLOWED_COMMANDS: dict[str, frozenset[CommandKind]] = {
    StageValue.INIT: frozenset(),
    StageValue.STAGE1_CREATING: frozenset(),
    StageValue.STAGE1_COMPLETE: frozenset({CommandKind.SELECT_ROLE, CommandKind.EXIT_GAME}),
    StageValue.STAGE2_REENACTING: frozenset(
        {
            CommandKind.CHOOSE_OPTION,
            CommandKind.FREE_INPUT,
            CommandKind.ROLLBACK_TO_EVENT,
            CommandKind.EXIT_GAME,
        }
    ),
    StageValue.STAGE2_COMPLETE: frozenset(
        {CommandKind.ENTER_STAGE3, CommandKind.EXIT_GAME}
    ),
    StageValue.STAGE3_EXTENDING: frozenset(
        {
            CommandKind.CHOOSE_OPTION,
            CommandKind.FREE_INPUT,
            CommandKind.ROLLBACK_TO_EVENT,
            CommandKind.CONFIRM_ENDING,
            CommandKind.EXIT_GAME,
        }
    ),
    StageValue.ENDED: frozenset(),
}


class EventType(StrEnum):
    """领域事件类型：游戏事实的载体。"""

    SESSION_STARTED = "session_started"
    MATERIAL_IMPORTED = "material_imported"
    SCRIPT_GENERATED = "script_generated"
    ROLE_SELECTED = "role_selected"
    NARRATIVE_ADVANCED = "narrative_advanced"
    PROPOSALS_GENERATED = "proposals_generated"
    PROPOSALS_VERIFIED = "proposals_verified"
    INTERACTION_OFFERED = "interaction_offered"
    PLAYER_ACTION_RECORDED = "player_action_recorded"
    AGENT_REACTIONS_DONE = "agent_reactions_done"
    STAGE_TRANSITIONED = "stage_transitioned"
    ROLLBACK_EXECUTED = "rollback_executed"


class ErrorDomain(StrEnum):
    """对外错误域命名空间（spec 错误决策）。"""

    INPUT = "input"
    CONTENT = "content"
    SEARCH = "search"
    LLM = "llm"
    GAME = "game"
    SESSION = "session"
    AUTH = "auth"
    PERSISTENCE = "persistence"
    PROTOCOL = "protocol"
    INTERNAL = "internal"


class UserRole(StrEnum):
    """账号角色（ADR-0002）：平台超管 / 教师 / 学生。"""

    SUPER_ADMIN = "super_admin"
    TEACHER = "teacher"
    STUDENT = "student"


class MessageCategory(StrEnum):
    """前端渲染类别：叙事消息 / 角色发言 / 系统提示 / 当前交互。"""

    NARRATIVE = "narrative"
    CHARACTER_SPEECH = "character_speech"
    SYSTEM = "system"
    INTERACTION = "interaction"
