"""角色 Agent：三层分离（identity / memory / director）精简版。

基于 design_01 §4。MVP 阶段聚焦机制：
- 三层结构保留（identity 稳定 prompt、memory 分层记忆、director 阶段指令）
- 每轮 `respond()` 只调一次 LLM；输出为提议（proposal）或发言（文本）
- 剧情质量验证 deferred，此处只保证结构正确与可调度
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.game.types import CharacterSetting, PlayerAction, Proposal
from app.domain.llm import LLMService
from app.infrastructure.errx import codes, new, wrap

logger = logging.getLogger("wenjing.agents.character")


@dataclass
class CharacterMemory:
    """角色的分层记忆。MVP 简化为工作记忆 + 个人日志 + 剧情上下文。"""

    working_memory: list[dict] = field(default_factory=list)  # 最近对话
    personal_log: list[str] = field(default_factory=list)     # 私有事件
    plot_context: str = ""
    current_direction: dict[str, str] = field(default_factory=dict)
    rejected: list[str] = field(default_factory=list)  # 被驳回提议描述（防重复）

    def snapshot(self) -> dict[str, Any]:
        return {
            "working_memory": self.working_memory,
            "personal_log": self.personal_log,
            "plot_context": self.plot_context,
            "current_direction": self.current_direction,
            "rejected": self.rejected,
        }

    def restore(self, data: dict[str, Any]) -> None:
        self.working_memory = data["working_memory"]
        self.personal_log = data["personal_log"]
        self.plot_context = data["plot_context"]
        self.current_direction = data["current_direction"]
        self.rejected = data["rejected"]


class CharacterIdentity:
    """稳定角色身份，全场不变。来源于 Script.character_settings。"""

    def __init__(self, setting: CharacterSetting) -> None:
        self.name = setting.name
        self.public_background = setting.public_background
        self.personality_traits = setting.personality_traits
        self.voice_style = ""

    def to_system_prompt(self) -> str:
        return (
            f"你是{self.name}。背景：{self.public_background}。"
            f"性格：{'、'.join(self.personality_traits)}。"
        )


class CharacterAgent:
    """单个角色 Agent，三层分离：identity + memory + director。"""

    def __init__(self, setting: CharacterSetting, llm: LLMService) -> None:
        self.identity = CharacterIdentity(setting)
        self.memory = CharacterMemory()
        self.llm = llm
        self._proposal_seq = 0

    async def propose_action(self, stage: str) -> Proposal:
        """按剧情上下文提出一个行动提议（一次 LLM 调用）。MVP 输出可 mock。"""
        system = self.identity.to_system_prompt()
        user = self._build_user_message(stage, instruction="propose_action")
        try:
            raw = await self.llm.chat(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                purpose=UsagePurpose.AGENT,
            )
        except Exception as exc:
            raise wrap(exc, codes.LLM_CALL_FAILED, extra={"reason": str(exc)}) from exc

        self._proposal_seq += 1
        text = raw.strip() or "（无提议）"
        self.memory.personal_log.append(f"提议：{text}")
        self.memory.rejected.append(text)  # 记录提出过，避免重复
        return Proposal(
            proposal_id=self._proposal_seq,
            proposed_by=self.identity.name,
            description=text,
        )

    async def react_to(self, player_action: PlayerAction, stage: str) -> str:
        """对玩家操作做出反应（模式 B/C；一次 LLM 调用）。"""
        system = self.identity.to_system_prompt()
        user = self._build_user_message(stage, instruction="react")
        raw = await self.llm.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            purpose=UsagePurpose.AGENT,
        )
        text = raw.strip()
        self.memory.working_memory.append({"role": self.identity.name, "content": text})
        logger.debug(
            "character_react",
            extra={"name": self.identity.name, "text": text},
        )
        return text

    def revise_proposal(self, suggestion: str | None) -> Proposal:
        """依据验证反馈重提。MVP 从 rejections 推导即可，不额外调 LLM。"""
        self._proposal_seq += 1
        hint = f"（修正：{suggestion}）" if suggestion else ""
        return Proposal(
            proposal_id=self._proposal_seq,
            proposed_by=self.identity.name,
            description=f"修订提议{hint}",
        )

    def _build_user_message(self, stage: str, instruction: str) -> str:
        stage_hint = {
            "stage2": "你处于剧情还原阶段，按课文原情节行动。",
            "stage3": "你处于剧情续写阶段，设定内自由发挥。",
        }.get(stage, "")
        return (
            f"{stage_hint} 剧情上下文：{self.memory.plot_context or '（无）'}\n"
            f"当前处境：{self.memory.current_direction or '（无）'}\n"
            f"任务：{instruction}"
        )


class CharacterAgentManager:
    """角色 Agent 集群管理器（design_01 §4.6 精简版）。"""

    def __init__(self, llm: LLMService, player_role: str | None = None) -> None:
        self.llm = llm
        self.agents: dict[str, CharacterAgent] = {}
        self.player_role: str | None = player_role

    def create_agents(self, characters: list[CharacterSetting]) -> None:
        for setting in characters:
            self.agents[setting.name] = CharacterAgent(setting, self.llm)
            if setting.is_player_playable:
                self.player_role = setting.name

    def active_names(self, *, include_player: bool = False) -> list[str]:
        return [n for n in self.agents if include_player or n != self.player_role]

    def get(self, name: str) -> CharacterAgent:
        if name not in self.agents:
            raise new(codes.AGENT_NOT_IN_SESSION, extra={"name": name})
        return self.agents[name]

    def broadcast_plot_context(self, summary: str) -> None:
        for agent in self.agents.values():
            agent.memory.plot_context = summary

    def broadcast_direction(self, direction: dict[str, str]) -> None:
        for agent in self.agents.values():
            agent.memory.current_direction = direction

    def snapshot_memories(self) -> dict[str, dict[str, Any]]:
        return {name: agent.memory.snapshot() for name, agent in self.agents.items()}

    def restore_memories(self, snapshot: dict[str, dict[str, Any]]) -> None:
        for name, data in snapshot.items():
            self.agents[name].memory.restore(data)
