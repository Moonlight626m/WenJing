"""角色 Agent：基于 LangChain agent + 工具的自主查询式实现（ADR-0004）。

三层分离（identity / memory / director 精简版）保留，但响应生成从"一次性拼装
上下文后单次 LLM 调用"升级为"LangChain 工具调用 Agent"：
- identity 仍是稳定 system prompt（`create_agent(system_prompt=...)`）；
- memory 仍是分层记忆，并作为 `view_my_memory` 工具的数据源；
- 剧情上下文 / 当前矛盾 / 世界进度不再由引擎强行灌入 prompt，而是由 Agent 通过
  工具（`view_world_progress` 等，见 `agents/tools.py`）**按需查询**。
- 每次生成仍以一次 `ainvoke` 为接缝；模型按需决定调用哪些工具（可能多轮往返，
  每轮单独计量）。
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage

from app.domain.agents.chat_model import WenjingChatModel
from app.domain.agents.tools import WorldView, build_character_tools
from app.domain.game.types import CharacterSetting, PlayerAction, Proposal
from app.domain.llm import LLMService
from app.infrastructure.errx import Error, codes, exc_reason, new, wrap

logger = logging.getLogger("wenjing.agents.character")

#: 可见文本增量回调（同步签名；WS 出口由调用方自行缓冲/下发）。
OnDelta = Callable[[str], None]

#: 阶段任务指令（PhaseDirector 式集中，jubensha-ai 调研参考点 #4）：
#: stage 别名 → 该阶段的任务框架。运行期所有角色通用、随阶段切换——与 identity
#: （全场不变）的区别就在这里。新增阶段在此登记一行，不要在各调用点散装 if。
STAGE_DIRECTIVES: dict[str, str] = {
    "stage2": "你处于剧情还原阶段，按课文原情节行动。",
    "stage3": "你处于剧情续写阶段，设定内自由发挥。",
}


@dataclass
class CharacterMemory:
    """角色的分层记忆。MVP 简化为工作记忆 + 个人日志 + 剧情上下文。"""

    working_memory: list[dict] = field(default_factory=list)  # 最近对话
    personal_log: list[str] = field(default_factory=list)  # 私有事件
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
        self.speech_style = setting.speech_style
        self.knows = setting.knows
        self.not_knows = setting.not_knows
        self.voice_style = ""

    def to_system_prompt(self) -> str:
        parts = [
            f"你是{self.name}。",
            f"背景：{self.public_background}。",
            f"性格：{'、'.join(self.personality_traits)}。",
        ]
        if self.speech_style:
            parts.append(f"说话风格：{self.speech_style}。")
        if self.knows or self.not_knows:
            # 知识边界保持结构化、逐条列出（不压平成一句）：not_knows 是**禁出
            # 清单**，逐条项目的显著性远高于压平叙述（jubensha-ai 调研参考点 #3
            # 的「公开必须是显式动作」化到 prompt 层就是这份清单）。
            parts.append("你知道的事：")
            for item in self.knows:
                parts.append(f"- {item}")
            if self.not_knows:
                parts.append(
                    "你不知道的事（**绝不能说出、也不能据此行动**；被问及"
                    "就以符合身份的方式回应：困惑、岔开或按你的立场表态）："
                )
                for item in self.not_knows:
                    parts.append(f"- {item}")
        parts.append(
            "你可以调用工具查询当前世界进度与剧情上下文；需要这些信息时先查询，"
            "再给出符合身份的行动，不要凭空编造未发生的情节。"
        )
        return "\n".join(parts)


class CharacterAgent:
    """单个角色 Agent：identity + memory + LangChain 工具调用执行器。"""

    def __init__(self, setting: CharacterSetting, llm: LLMService, world: WorldView) -> None:
        self.identity = CharacterIdentity(setting)
        self.memory = CharacterMemory()
        self.llm = llm
        self._proposal_seq = 0
        self._model = WenjingChatModel(service=llm)
        self._tools = build_character_tools(memory=self.memory, world=world)
        self._executor = create_agent(
            self._model,
            tools=self._tools,
            system_prompt=self.identity.to_system_prompt(),
        )

    async def propose_action(self, stage: str) -> Proposal:
        """按当前世界状态提出一个行动提议（工具调用 Agent 跑一轮）。"""
        text = await self._run(stage, instruction="propose_action")
        self._proposal_seq += 1
        description = text or "（无提议）"
        self.memory.personal_log.append(f"提议：{description}")
        self.memory.rejected.append(description)  # 记录提出过，避免重复
        return Proposal(
            proposal_id=self._proposal_seq,
            proposed_by=self.identity.name,
            description=description,
        )

    async def react_to(
        self,
        player_action: PlayerAction,
        stage: str,
        *,
        on_delta: OnDelta | None = None,
    ) -> str:
        """对玩家操作做出反应（模式 B/C）。

        `on_delta` 非空时走流式（#59 / ADR-0005 §10）：可见文本逐段回调，TTFT 只受
        首 token 影响；**返回值仍是最终答复**——工具轮的引导语是临时文本，不进返回值。
        调用方用返回值持久化 `character_speech`，由终态规则覆盖前端已渲染的临时文本。
        """
        detail = player_action.text or f"选项 {player_action.option_id}"
        extra = f"玩家刚刚做出了行动：{player_action.type}（{detail}）。请以角色身份回应。"
        if on_delta is None:
            text = await self._run(stage, instruction="react", extra=extra)
        else:
            text = await self._run_streaming(
                stage, instruction="react", extra=extra, on_delta=on_delta
            )
        if text:
            self.memory.working_memory.append({"role": self.identity.name, "content": text})
        logger.debug(
            "character_react",
            extra={"wj_extra": {"name": self.identity.name, "text": text}},
        )
        return text

    async def revise_proposal(self, stage: str, suggestion: str | None) -> Proposal:
        """依据验证反馈重新提案（工具调用 Agent 跑一轮，同 propose_action）。

        把原提议与驳回理由显式写进任务提示，角色据此调整思路——被驳回的提议已
        在 `propose_action` 进过 `memory.rejected`，Agent 可经 `view_my_memory`
        自查，避免换个措辞重提同一方案。MVP 的同步模板拼字版本（不调 LLM）仅剩
        机制用途，已由本方法替代。
        """
        original = self.memory.rejected[-1] if self.memory.rejected else None
        feedback = f"你的上一个提议已被驳回，理由：{suggestion or '不合规'}。"
        if original:
            feedback += f"原提议是：「{original.removeprefix('提议：')}」。请换个方向重新提议。"
        text = await self._run(stage, instruction="propose_action", extra=feedback)
        self._proposal_seq += 1
        description = text or "（无提议）"
        self.memory.personal_log.append(f"提议：{description}")
        self.memory.rejected.append(description)  # 记录提出过，避免重复
        return Proposal(
            proposal_id=self._proposal_seq,
            proposed_by=self.identity.name,
            description=description,
        )

    async def _run(self, stage: str, *, instruction: str, extra: str = "") -> str:
        """驱动 LangChain 执行器一轮，返回最终 AI 文本。"""
        message = self._build_user_message(stage, instruction=instruction, extra=extra)
        try:
            result = await self._executor.ainvoke({"messages": [HumanMessage(content=message)]})
        except Error:
            # 已经是带码的 errx.Error（含 `LLM_TIMEOUT`）：再包一层会把 #65 分列出来的
            # 超时码抹平成 `LLM_CALL_FAILED`，上层就再也看不出该调超时还是该换 key。
            raise
        except Exception as exc:
            raise wrap(exc, codes.LLM_CALL_FAILED, extra={"reason": exc_reason(exc)}) from exc
        return _final_text(result.get("messages", []))

    async def _run_streaming(
        self,
        stage: str,
        *,
        instruction: str,
        extra: str = "",
        on_delta: OnDelta,
    ) -> str:
        """驱动 LangChain 执行器一轮的流式版本，返回**最终答复**。

        用 `stream_mode="messages"` 拿每个节点产出的消息增量，只认模型节点给出的
        `AIMessageChunk`（工具节点产出的是 `ToolMessage`，跳过）：
        - 文本增量即时回调，不在本地缓冲——缓冲会把 TTFT 吃掉；
        - `tool_call_chunks` 只走工具通道，不作为文本下发；但**同一段里的 content
          照常发出**——有的 provider 把引导语与 tool_call 塞进同一个 chunk，按段
          整体丢弃会把玩家该看到的话直接吞掉；
        - 按消息 id 归并增量，流末仍用 `_final_text` 取「最后一条无工具调用的 AI
          文本」作为返回值，故工具轮的引导语不会混进持久发言。
        """
        message = self._build_user_message(stage, instruction=instruction, extra=extra)
        merged: dict[str, AIMessageChunk] = {}
        last_key = ""
        try:
            async for chunk, _meta in self._executor.astream(
                {"messages": [HumanMessage(content=message)]}, stream_mode="messages"
            ):
                if not isinstance(chunk, AIMessageChunk):
                    continue
                # provider 不给 id 时沿用上一条的键：这些增量属于同一条消息，
                # 各自成键会让流末的归并拿到一堆半截消息
                key = chunk.id or last_key or "anon"
                last_key = key
                merged[key] = merged[key] + chunk if key in merged else chunk
                text = _message_text(chunk)
                if text:
                    on_delta(text)
        except Error:
            # 同上：保住 `LLM_TIMEOUT` 这类已分列的码。
            raise
        except Exception as exc:
            raise wrap(exc, codes.LLM_CALL_FAILED, extra={"reason": exc_reason(exc)}) from exc
        return _final_text(list(merged.values()))

    def _build_user_message(self, stage: str, *, instruction: str, extra: str = "") -> str:
        parts = [STAGE_DIRECTIVES.get(stage, "")]
        if extra:
            parts.append(extra)
        parts.append(f"任务：{instruction}（必要时先用工具查询世界进度与剧情上下文）")
        return "\n".join(p for p in parts if p)


def _final_text(messages: list[BaseMessage]) -> str:
    """取最后一条**无工具调用**的 AI 文本（即最终答复）。

    工具调用轮的 AIMessage 可能同时携带引导语与 tool_calls，若只取"最后一条非空
    AI 文本"，在末轮 content 为空或被 recursion_limit 截断时会误取中间引导语。
    故排除带 tool_calls 的消息，只认最终答复；找不到则返回空串。

    流式路径把每段增量按消息 id 归并成 `AIMessageChunk` 后同样喂进本函数——
    `AIMessageChunk` 是 `AIMessage` 的子类，归并时 `tool_call_chunks` 会升级成
    `tool_calls`，故「工具轮」判据对两条路径一致。
    """
    for message in reversed(messages):
        if not isinstance(message, AIMessage):
            continue
        if getattr(message, "tool_calls", None):
            continue
        return _message_text(message).strip()
    return ""


def _message_text(message: BaseMessage) -> str:
    """取出消息的纯文本内容（content 可能是分块列表）；**不裁剪**，增量拼接靠它。"""
    content = message.content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return "" if content is None else str(content)


class CharacterAgentManager:
    """角色 Agent 集群管理器（design_01 §4.6 精简版）。"""

    def __init__(
        self,
        llm: LLMService,
        world: WorldView,
        player_role: str | None = None,
    ) -> None:
        self.llm = llm
        self.world = world
        self.agents: dict[str, CharacterAgent] = {}
        self.player_role: str | None = player_role

    def create_agents(self, characters: list[CharacterSetting]) -> None:
        for setting in characters:
            # 机制层知识边界：每个角色拿**自己**的裁剪视图（在场/可公开），
            # 未裁剪的全局视图不进任何 agent 的工具闭包。
            scoped = self.world.bind(setting.name)
            self.agents[setting.name] = CharacterAgent(setting, self.llm, scoped)
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
