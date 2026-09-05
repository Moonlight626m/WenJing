"""错误码集中注册表。

采用 `WJ-<模块>-<编号>` 分层语义，编码为整数 code（段内连续）。
所有错误码在此处统一注册，新增错误在此登记即可。
"""

from __future__ import annotations

from app.errx._registry import register

# ===== 会话（SESS）=====
SESS_NOT_FOUND = 1001
SESS_ENDED = 1002
SESS_CONFLICT = 1003                # 乐观锁版本冲突（并发命令）

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

# ===== 内容（CNT）=====
CNT_UNSUPPORTED_GENRE = 6001        # 课文体裁不支持（非叙事类）
CNT_INSUFFICIENT_SOURCE = 6002      # 原文分析不足以产出合法剧本（issue #11）
CNT_GENERATION_FAILED = 6003        # Stage1 生成/校验重试后仍失败（issue #11）

# ===== 导入（INP）=====
INP_EMPTY_MATERIAL = 7001           # 课文内容为空
INP_UNSUPPORTED_EXTENSION = 7002    # 上传文件扩展名不支持
INP_INVALID_ENCODING = 7003         # 上传字节无法按受支持编码解码
INP_TOO_LARGE = 7004                # 课文超出大小上限

# ===== 检索（SEARCH，issue #10 安全 RAG）=====
SEARCH_UNAVAILABLE = 8001           # 搜索 provider 不可用/失败
SEARCH_BLOCKED_TARGET = 8002        # SSRF/DNS 校验拒绝目标（私有/回环/元数据）
SEARCH_TIMEOUT = 8003               # 抓取连接/读取超时

# ===== 协议（PRT）=====
PRT_MALFORMED_MESSAGE = 9001        # 请求消息/标识格式非法
PRT_UNKNOWN_COMMAND = 9002          # 未知的命令类型


def register_all() -> None:
    """注册全部错误码（应用启动时调用一次，幂等）。"""

    register(SESS_NOT_FOUND, "session {id} not found", is_affect_stability=False)
    register(SESS_ENDED, "session {id} already ended", is_affect_stability=False)
    register(
        SESS_CONFLICT,
        "session {id} version conflict (expected {expected})",
        is_affect_stability=False,
    )

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

    register(CNT_UNSUPPORTED_GENRE, "unsupported genre: {genre}", is_affect_stability=False)
    register(
        CNT_INSUFFICIENT_SOURCE,
        "insufficient source material: {reason}",
        is_affect_stability=False,
    )
    register(CNT_GENERATION_FAILED, "stage1 generation failed after retries: {reason}")

    register(INP_EMPTY_MATERIAL, "material text is empty", is_affect_stability=False)
    register(
        INP_UNSUPPORTED_EXTENSION,
        "unsupported file extension: {ext}",
        is_affect_stability=False,
    )
    register(
        INP_INVALID_ENCODING,
        "cannot decode material bytes: {reason}",
        is_affect_stability=False,
    )
    register(INP_TOO_LARGE, "material exceeds size limit {max_chars}", is_affect_stability=False)

    register(SEARCH_UNAVAILABLE, "search unavailable: {reason}", is_affect_stability=False)
    register(
        SEARCH_BLOCKED_TARGET,
        "blocked network target: {reason}",
        is_affect_stability=False,
    )
    register(SEARCH_TIMEOUT, "fetch timed out: {url}")

    register(
        PRT_MALFORMED_MESSAGE,
        "malformed message: {reason}",
        is_affect_stability=False,
    )
    register(PRT_UNKNOWN_COMMAND, "unknown command: {kind}", is_affect_stability=False)
