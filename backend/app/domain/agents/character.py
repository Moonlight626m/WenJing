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
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, HumanMessage

from app.domain.agents.chat_model import WenjingChatModel
from app.domain.agents.prompting import (
    ACTION_LABELS,
    CHARACTER_MEMORY_LIMIT,
    build_character_prompt,
    build_character_system,
)
from app.domain.agents.tools import WorldView, build_character_tools
from app.domain.game.event import (
    EVENT_CHARACTER_CREATED,
    EVENT_CHARACTER_SPEECH,
    EVENT_PROPOSAL,
)
from app.domain.game.types import CharacterSetting, PlayerAction, Proposal
from app.domain.llm import LLMService
from app.infrastructure.errx import Error, codes, exc_reason, new, wrap

logger = logging.getLogger("wenjing.agents.character")

#: 可见文本增量回调（同步签名；WS 出口由调用方自行缓冲/下发）。
OnDelta = Callable[[str], None]


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
        # 旧快照可能存着无界记忆：恢复时统一收口到读取窗口
        self.trim()

    def add_personal_note(self, text: str) -> None:
        """记一条不会进 `rejected` 的个人事件（如干涉登场的前史）。"""
        self.personal_log.append(text)
        self.trim()

    def trim(self) -> None:
        """记忆是有界窗口：只保留最近 `CHARACTER_MEMORY_LIMIT` 条。

        事件流才是全量权威；快照/进程内记忆只是读取窗口，有界后每命令快照
        的存储量恒定，不再随回合数增长（O(n²) → O(n)）。
        """
        for entries in (self.working_memory, self.personal_log, self.rejected):
            if len(entries) > CHARACTER_MEMORY_LIMIT:
                del entries[:-CHARACTER_MEMORY_LIMIT]

    def clear(self) -> None:
        """原地清空记忆（保持对象身份——工具闭包持有本对象的引用，换对象会让
        `view_my_memory` 读到旧记忆）。全量事件重放前用它复位。"""
        self.working_memory = []
        self.personal_log = []
        self.plot_context = ""
        self.current_direction = {}
        self.rejected = []


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
        return build_character_system(
            name=self.name,
            public_background=self.public_background,
            personality_traits=self.personality_traits,
            speech_style=self.speech_style,
            knows=self.knows,
            not_knows=self.not_knows,
        )


class CharacterAgent:
    """单个角色 Agent：identity + memory + LangChain 工具调用执行器。"""

    def __init__(self, setting: CharacterSetting, llm: LLMService, world: WorldView) -> None:
        self.identity = CharacterIdentity(setting)
        self.memory = CharacterMemory()
        self.llm = llm
        self._proposal_seq = 0
        # system 一次构造、全场复用：同一角色+阶段逐字节稳定，动态内容只进 user。
        self._system_prompt = self.identity.to_system_prompt()
        self._model = WenjingChatModel(service=llm)
        self._tools = build_character_tools(memory=self.memory, world=world)
        self._executor = create_agent(
            self._model,
            tools=self._tools,
            system_prompt=self._system_prompt,
        )

    def record_proposal(self, description: str) -> None:
        """记一次提议到私有记忆。实时提案与事件重放共用，防两处写法漂移。"""
        self.memory.personal_log.append(f"提议：{description}")
        self.memory.rejected.append(description)  # 记录提出过，避免重复
        self.memory.trim()

    def record_speech(self, text: str) -> None:
        """记一次发言到工作记忆（实时回应与事件重放共用）。"""
        self.memory.working_memory.append(
            {"role": self.identity.name, "content": text}
        )
        self.memory.trim()

    async def propose_action(self, stage: str) -> Proposal:
        """按当前世界状态提出一个行动提议（工具调用 Agent 跑一轮）。"""
        text = await self._run(stage, instruction="propose_action")
        self._proposal_seq += 1
        description = text or "（无提议）"
        self.record_proposal(description)
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
        action_label = ACTION_LABELS.get(player_action.type, player_action.type)
        extra = f"玩家刚刚做出了行动：{action_label}「{detail}」。请以角色身份回应。"
        if on_delta is None:
            text = await self._run(stage, instruction="react", extra=extra)
        else:
            text = await self._run_streaming(
                stage, instruction="react", extra=extra, on_delta=on_delta
            )
        if text:
            self.record_speech(text)
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
        self.record_proposal(description)
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
        return build_character_prompt(
            system_prompt=self._system_prompt,
            stage=stage,
            instruction=instruction,
            extra=extra,
        ).user


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

    def add_character(self, setting: CharacterSetting) -> None:
        """运行期新增 NPC（M6 干涉 `add_character`；design §B5）。

        与剧本角色走**同一条创建路径**（裁剪视图 + player_role 缺省空）。
        初始记忆为空；「为何在此」的 provenance 由 `derive_memories` 从
        `character_created` 事件折叠（实时与重放同一写者，不双计）。
        """
        if setting.name in self.agents:
            return  # 幂等：重放/实时双写同一次 character_created
        self.create_agents([setting])

    def remove_character(self, name: str) -> None:
        """移除运行期新增角色（回溯到 `character_created` 之前 = 从未存在）。"""
        self.agents.pop(name, None)

    def active_names(self, *, include_player: bool = False) -> list[str]:
        return [n for n in self.agents if include_player or n != self.player_role]

    def get(self, name: str) -> CharacterAgent:
        if name not in self.agents:
            raise new(codes.AGENT_NOT_IN_SESSION, extra={"name": name})
        return self.agents[name]

    def broadcast_plot_context(self, summary: str) -> None:
        """全局广播剧情摘要到 `plot_context`。

        **write-only**：当前没有任何工具/prompt 读取它。摘要包含角色不在场的
        内容，直接暴露会破坏知识边界；若未来要接入，必须先按 viewer 裁剪。
        角色读剧情请走 `view_plot_log`（事件派生的 visible 摘要）。
        """
        for agent in self.agents.values():
            agent.memory.plot_context = summary

    def broadcast_direction(self, direction: dict[str, str]) -> None:
        """全局广播当前处境到 `current_direction`（同样 write-only，见上）。"""
        for agent in self.agents.values():
            agent.memory.current_direction = direction

    def snapshot_memories(self) -> dict[str, dict[str, Any]]:
        return {name: agent.memory.snapshot() for name, agent in self.agents.items()}

    def restore_memories(self, snapshot: dict[str, dict[str, Any]]) -> None:
        for name, data in snapshot.items():
            # 快照可能引用当前分支已不存在的动态角色（回溯到创建前）——跳过
            agent = self.agents.get(name)
            if agent is not None:
                agent.memory.restore(data)

    def clear_memories(self) -> None:
        """原地清空全部角色记忆（保持 agent/memory 对象身份——工具闭包持有引用，
        换对象会让 `view_my_memory` 读到旧记忆）。全量事件重放前用它复位。"""
        for agent in self.agents.values():
            agent.memory.clear()

    def derive_memories(self, events: Iterable[dict[str, Any]]) -> None:
        """把一段事件折叠进角色记忆（M0：记忆由事件重建，快照只是兼容缓存）。

        与实时路径**同一写入函数**（`record_proposal` / `record_speech`），
        不在重放侧另写一份：
        - `proposal {proposed_by, description}` → 该角色 personal_log/rejected；
        - `character_speech {speaker, text}` → 该角色 working_memory。

        plot/direction 广播不在其列——`_replay_event` 已按事件顺序重放（赋值幂等）。
        调用方契约：events 必须是记忆基线（快照缓存）**之后**的事件段；
        与基线重叠会重复追加。只折叠本运行时已创建的角色，其余静默跳过。
        """
        for ev in events:
            etype = ev.get("event_type") or ev.get("type") or ""
            payload = ev.get("payload") or {}
            if etype == EVENT_PROPOSAL:
                name = payload.get("proposed_by")
                agent = self.agents.get(str(name)) if name else None
                if agent is None:
                    continue
                agent.record_proposal(str(payload.get("description", "")) or "（无提议）")
            elif etype == EVENT_CHARACTER_SPEECH:
                speaker = payload.get("speaker")
                agent = self.agents.get(str(speaker)) if speaker else None
                if agent is None:
                    continue
                text = str(payload.get("text", ""))
                if text:
                    agent.record_speech(text)
            elif etype == EVENT_CHARACTER_CREATED:
                # 干涉新建角色的 provenance 记忆（「为何在此」）：与剧本角色
                # 一样走事件折叠，回溯到创建之前该记忆随角色一起消失
                name = payload.get("name")
                agent = self.agents.get(str(name)) if name else None
                if agent is None:
                    continue
                origin = payload.get("origin")
                brief = str(payload.get("public_background", ""))
                if origin == "player_intervention" and brief:
                    agent.memory.add_personal_note(f"你因玩家的干涉而登场：{brief}")
