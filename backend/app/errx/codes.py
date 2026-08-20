"""错误码集中注册表。

采用 `WJ-<模块>-<编号>` 分层语义，编码为整数 code（段内连续）。
所有错误码在此处统一注册，新增错误在此登记即可。
"""

from __future__ import annotations

from app.errx._registry import register

# ===== 会话（SESS）=====
SESS_NOT_FOUND = 1001
SESS_ENDED = 1002

# ===== 引擎（ENG）=====
ENG_INVALID_TRANSITION = 2001      # 非法 Stage 转换
ENG_ROLLBACK_TARGET_MISSING = 2002  # 回溯目标事件不存在
ENG_ROLLBACK_OVERFLOW = 2003        # 回溯步数超出限制
ENG_PLAYER_ACTION_INVALID = 2004    # 玩家操作非法/缺字段
ENG_NOT_RUNNING = 2005              # 引擎未在运行，无法处理操作

# ===== Agent（AGENT）=====
AGENT_NOT_IN_SESSION = 3001         # 指定角色不在当前会话
AGENT_PROPOSAL_ALL_REJECTED = 3002  # 全部角色提议被驳回（僵局）

# ===== LLM（LLM）=====
LLM_CALL_FAILED = 4001              # LLM 调用失败/超时
LLM_OUTPUT_PARSE_FAILED = 4002      # LLM 结构化输出解析失败
LLM_UNKNOWN_MODEL = 4003            # 请求了未登记/未知的 provider 或模型

# ===== 配置（CFG）=====
CFG_UNKNOWN_PROVIDER = 5001         # 未知的 LLM provider


def register_all() -> None:
    """注册全部错误码（应用启动时调用一次，幂等）。"""

    register(SESS_NOT_FOUND, "session {id} not found", is_affect_stability=False)
    register(SESS_ENDED, "session {id} already ended", is_affect_stability=False)

    register(ENG_INVALID_TRANSITION, "invalid stage transition from {src} to {dst}")
    register(
        ENG_ROLLBACK_TARGET_MISSING,
        "rollback target event {event_id} does not exist",
        is_affect_stability=False,
    )
    register(
        ENG_ROLLBACK_OVERFLOW,
        "rollback of {steps} steps exceeds limit {max_steps}",
        is_affect_stability=False,
    )
    register(
        ENG_PLAYER_ACTION_INVALID,
        "invalid player action: {reason}",
        is_affect_stability=False,
    )
    register(ENG_NOT_RUNNING, "engine {session_id} is not running")

    register(AGENT_NOT_IN_SESSION, "character {name} not in session", is_affect_stability=False)
    register(
        AGENT_PROPOSAL_ALL_REJECTED,
        "all character proposals rejected ({stage})",
        is_affect_stability=False,
    )

    register(LLM_CALL_FAILED, "llm call failed: {reason}")
    register(LLM_OUTPUT_PARSE_FAILED, "failed to parse llm structured output: {target}")
    register(LLM_UNKNOWN_MODEL, "unknown llm model/provider: {provider}")

    register(CFG_UNKNOWN_PROVIDER, "unknown llm provider: {provider}", is_affect_stability=False)
