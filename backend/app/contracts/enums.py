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
    # Stage3 玩家干涉世界（建场景/拉入角色）：自然语言 → ProducerAgent 解析。
    INTERVENE = "intervene"


# 每阶段允许的命令（allowed_commands 约束，runtime 校验依据）
ALLOWED_COMMANDS: dict[str, frozenset[CommandKind]] = {
    StageValue.INIT: frozenset(),
    StageValue.STAGE1_CREATING: frozenset(),
    StageValue.STAGE1_COMPLETE: frozenset({CommandKind.SELECT_ROLE, CommandKind.EXIT_GAME}),
    StageValue.STAGE2_REENACTING: frozenset(
        {
            # 还原阶段是纯 IO 播放：只接受选项，不接受自由输入（design
            # play-through-redesign §A4）。FREE_INPUT 保留给 Stage3。
            CommandKind.CHOOSE_OPTION,
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
            # CommandKind.INTERVENE 由 M6 接线（ProducerAgent 就绪后才允许，
            # 否则「允许的命令」会落到引擎的非法命令兜底）
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
    ASSET_READY = "asset_ready"
    # 续写目标（Stage3）：定下目标 / 某个目标达成
    STAGE3_GOALS_SET = "stage3_goals_set"
    STAGE3_GOAL_ACHIEVED = "stage3_goal_achieved"
    # 伪分支播放（方案 branch-montage-dm §6）：分支进入/完成，分支内
    # plot_advancement 带 branch_key（主干为 null）区分两条推进线。
    BRANCH_TAKEN = "branch_taken"
    BRANCH_COMPLETED = "branch_completed"
    # Stage2 珊瑚图纯 IO 播放（design play-through-redesign §A4）
    REPLAY_NODE_ENTERED = "replay_node_entered"
    REPLAY_NARRATION = "replay_narration"
    REPLAY_CHOICE = "replay_choice"
    REPLAY_ENDING_REACHED = "replay_ending_reached"
    # Stage3 探索/场景/干涉（§B3–B5）
    EXPLORATION_SETTLED = "exploration_settled"
    SCENE_CREATED = "scene_created"
    SCENE_SWITCHED = "scene_switched"
    SCENE_UNLOCK_REJECTED = "scene_unlock_rejected"
    CHARACTER_CREATED = "character_created"
    CHARACTER_PULLED_IN = "character_pulled_in"
    INTERVENTION_REQUESTED = "intervention_requested"
    INTERVENTION_REJECTED = "intervention_rejected"
    WORLD_FACT = "world_fact"
    # 离线 tick 的提示（§B6）：不写详细摘要，只指路时间线。
    OFFLINE_HINT = "offline_hint"


class ErrorDomain(StrEnum):
    """对外错误域命名空间（spec 错误决策）。"""

    INPUT = "input"
    CONTENT = "content"
    SEARCH = "search"
    MEDIA = "media"
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


class ScriptStatus(StrEnum):
    """可复用剧本实体的生命周期（ADR-0002 §3）：草稿→发布→下架。"""

    DRAFT = "draft"
    PUBLISHED = "published"
    UNPUBLISHED = "unpublished"


class ScriptVisibility(StrEnum):
    """已发布剧本的可见性：同 org / 公开（跨 org）。"""

    ORG = "org"
    PUBLIC = "public"


class UsagePurpose(StrEnum):
    """LLM 调用用途（ADR-0002 §5 / issue #28 workflow 节点细分）。

    AGENT/VERIFY 服务于游戏运行时多 agent（Stage2/3）；其余为剧本生成
    workflow 的节点用途（#28 骨架：write_script 暂由 Stage1Generator 承担，
    #33 退役旧路径后 STAGE1 随之废弃）。
    """

    STAGE1 = "stage1"
    AGENT = "agent"
    VERIFY = "verify"
    COLLECT_MATERIALS = "collect_materials"
    DOUBTER = "doubter"
    DIVIDE_EVENTS = "divide_events"
    CHARACTER_DESIGN = "character_design"
    SCRIPT_WRITING = "script_writing"
    # 媒体图片审核 agent（ADR-0005 §6 / issue #45）：便宜模型结构化判定。
    IMAGE_REVIEW = "image_review"
    # 画师层（方案 branch-montage-dm §5）：SceneDesigner 内 LLM 转写层，
    # 把节拍/appearance/visual_notes 转写为画面语 prompt。
    SCENE_PROMPT = "scene_prompt"


class MessageCategory(StrEnum):
    """前端渲染类别：叙事消息 / 角色发言 / 系统提示 / 当前交互 / 资产就绪。"""

    NARRATIVE = "narrative"
    CHARACTER_SPEECH = "character_speech"
    SYSTEM = "system"
    INTERACTION = "interaction"
    # 运行期配图就绪（ADR-0005 §5，issue #56）：命令外事件路径推送，
    # 前端据此替换当前场景背景；不是聊天流消息，故不复用 ContentBlock。
    ASSET_READY = "asset_ready"
