"""引擎配置：集中管理可调参数（design_03 §6）。

MVP 聚焦机制，参数默认值对应 design_00 D11/D15 与 design_03 EngineConfig。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class EngineConfig:
    max_proposal_retries: int = 2       # 角色提议被驳回后最多重试 2 次
    checkpoint_interval: int = 20       # 预留：每 20 事件打快照（内存 MVP 未启用）
    max_rollback_steps: int = 100       # 最大回退步数
    max_concurrent_llm: int = 5         # 最大并行 LLM 调用数
    llm_timeout_seconds: int = 30
    stage3_rounds: int = 3              # MVP 续写有限轮次（目标导向收敛占位）
    max_events_in_memory: int = 5000    # 内存中最大事件数
