"""角色 Agent 的 LangChain 工具化实现测试（ADR-0004）。

覆盖三层：
1. `WenjingChatModel` 把 `LLMService` 的工具调用回复转成 `AIMessage.tool_calls`；
2. `build_character_tools` 的世界进度等工具可被调用且返回状态；
3. 引擎接线后，角色提议链路确实经过"模型请求工具 → 工具结果回填 → 最终提议"。
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.contracts.enums import UsagePurpose
from app.domain.agents.character import CharacterAgent, CharacterIdentity, _final_text
from app.domain.agents.chat_model import WenjingChatModel
from app.domain.agents.prompting import CHARACTER_MEMORY_LIMIT
from app.domain.agents.tools import build_character_tools
from app.domain.game.types import CharacterSetting
from app.domain.llm import LLMReply, ToolCall


class _FakeWorld:
    """最小 WorldView 假实现。"""

    def progress(self) -> dict[str, Any]:
        return {
            "stage": "stage2",
            "beat_cursor": 2,
            "total_beats": 3,
            "player_role": "李白",
            "ended": False,
        }

    def plot_log(self, limit: int = 5) -> list[str]:
        return ["[stage2] 三人在长安酒馆相遇"]

    def direction(self) -> dict[str, str]:
        return {"conflict": "杜甫想远游", "context": "长安酒馆"}

    def outline(self) -> list[dict[str, Any]]:
        return [{"scene_id": 1, "title": "相遇", "participants": ["李白"], "beats": ["相遇"]}]

    def roster(self) -> list[dict[str, Any]]:
        return [{"name": "李白", "public_background": "诗人", "is_player_role": True}]


class _Memory:
    def __init__(self) -> None:
        self.personal_log: list[str] = []
        self.rejected: list[str] = []
        self.working_memory: list[dict] = []


class ToolCallingLLM:
    """首轮请求工具、次轮给出最终答复的脚本化 LLM（仅测试用）。"""

    def __init__(self) -> None:
        self.tool_calls_seen: list[list[dict]] = []
        self.tool_results: list[str] = []
        self.final = "我提议按进度推进"

    async def chat(self, messages, *, session_id: str = "", purpose=None) -> str:
        return self.final

    async def chat_with_tools(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> LLMReply:
        self.tool_calls_seen.append(tools or [])
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        if not tool_msgs:
            return LLMReply(
                content="",
                tool_calls=(ToolCall(id="c1", name="view_world_progress", arguments={}),),
            )
        self.tool_results.append(tool_msgs[-1]["content"])
        return LLMReply(content=self.final)


# ===== 1. ChatModel 适配层 =====


async def test_chat_model_surfaces_tool_calls():
    llm = ToolCallingLLM()
    model = WenjingChatModel(service=llm)
    tools = build_character_tools(memory=_Memory(), world=_FakeWorld())
    bound = model.bind_tools(tools)

    result = await bound.ainvoke([HumanMessage(content="提出行动")])

    assert result.tool_calls
    assert result.tool_calls[0]["name"] == "view_world_progress"
    assert llm.tool_calls_seen, "工具 schema 应下发给底层 LLM"


# ===== 2. 工具本身 =====


def test_build_character_tools_exposes_world_progress():
    tools = build_character_tools(memory=_Memory(), world=_FakeWorld())
    by_name = {t.name: t for t in tools}
    payload = json.loads(by_name["view_world_progress"].invoke({}))
    assert payload["stage"] == "stage2"
    assert payload["total_beats"] == 3
    assert payload["player_role"] == "李白"
    assert json.loads(by_name["view_current_direction"].invoke({})) == {
        "conflict": "杜甫想远游",
        "context": "长安酒馆",
    }
    assert "view_plot_log" in by_name


def test_view_my_memory_returns_recent_speech_only():
    """角色能读到自己说过的话；窗口有界，且不夹带 write-only 的全局广播。"""
    memory = _Memory()
    memory.personal_log = [f"提议：{i}" for i in range(15)]
    memory.rejected = [f"驳回{i}" for i in range(15)]
    memory.working_memory = [
        {"role": "杜甫", "content": f"第{i}句"} for i in range(15)
    ]
    tools = build_character_tools(memory=memory, world=_FakeWorld())
    payload = json.loads({t.name: t for t in tools}["view_my_memory"].invoke({}))

    assert len(payload["recent_speech"]) == 10
    assert payload["recent_speech"][-1] == {"role": "杜甫", "content": "第14句"}
    assert all(entry["role"] == "杜甫" for entry in payload["recent_speech"])
    assert len(payload["personal_log"]) == 10
    assert len(payload["rejected"]) == 10
    assert "plot_context" not in payload
    assert "current_direction" not in payload


def test_final_text_ignores_tool_call_preamble():
    """工具轮里的引导语不得被当成最终答复（末轮为空/截断时尤其）。"""
    messages = [
        HumanMessage(content="提出行动"),
        AIMessage(
            content="让我先查一下世界进度。",
            tool_calls=[
                {"name": "view_world_progress", "args": {}, "id": "c1", "type": "tool_call"}
            ],
        ),
        ToolMessage(content="stage=stage2", tool_call_id="c1"),
        AIMessage(content=""),
    ]
    assert _final_text(messages) == ""

    messages[-1] = AIMessage(content="我提议按进度推进")
    assert _final_text(messages) == "我提议按进度推进"


# ===== 3. 角色 Agent 全链路 =====


async def test_character_agent_queries_world_before_proposing():
    llm = ToolCallingLLM()
    agent = CharacterAgent(
        CharacterSetting(name="杜甫", public_background="诗人"),
        llm,
        _FakeWorld(),
    )

    proposal = await agent.propose_action("stage2")

    assert proposal.description == llm.final
    assert proposal.proposed_by == "杜甫"
    assert llm.tool_results, "模型应收到工具执行结果"
    assert "stage2" in llm.tool_results[-1], "工具结果应包含世界进度"


# ===== 4. 身份边界与反应体裁 =====


def test_character_memory_is_bounded():
    """记忆是读取窗口：写入时收口到最近 N 条，快照不会随回合线性膨胀。"""
    agent = CharacterAgent(
        CharacterSetting(name="杜甫", public_background="诗人"),
        ToolCallingLLM(),
        _FakeWorld(),
    )
    for i in range(CHARACTER_MEMORY_LIMIT + 5):
        agent.record_proposal(f"提议{i}")
        agent.record_speech(f"第{i}句")
        agent.memory.add_personal_note(f"前史{i}")

    assert len(agent.memory.personal_log) == CHARACTER_MEMORY_LIMIT
    assert agent.memory.personal_log[-1] == f"前史{CHARACTER_MEMORY_LIMIT + 4}"
    assert len(agent.memory.rejected) == CHARACTER_MEMORY_LIMIT
    assert len(agent.memory.working_memory) == CHARACTER_MEMORY_LIMIT
    assert agent.memory.working_memory[-1]["content"] == f"第{CHARACTER_MEMORY_LIMIT + 4}句"


def test_character_memory_does_not_bleed_between_agents():
    """A 的 `view_my_memory` 只回 A 自己的发言，不会串到别的角色。"""
    du = CharacterAgent(
        CharacterSetting(name="杜甫", public_background="诗人"),
        ToolCallingLLM(),
        _FakeWorld(),
    )
    li = CharacterAgent(
        CharacterSetting(name="李白", public_background="诗人"),
        ToolCallingLLM(),
        _FakeWorld(),
    )
    du.record_speech("甫说")
    li.record_speech("白说")

    tools = {t.name: t for t in build_character_tools(memory=du.memory, world=_FakeWorld())}
    payload = json.loads(tools["view_my_memory"].invoke({}))
    assert payload["recent_speech"] == [{"role": "杜甫", "content": "甫说"}]
    assert li.memory.working_memory == [{"role": "李白", "content": "白说"}]


def test_identity_prompt_states_behavior_boundaries():
    identity = CharacterIdentity(
        CharacterSetting(
            name="杜甫",
            public_background="诗人",
            personality_traits=["沉郁", "重情"],
            knows=["与李白同游"],
            not_knows=["高适的军情"],
        )
    )
    prompt = identity.to_system_prompt()
    assert "只能以这个角色的身份" in prompt
    assert "不写旁白" in prompt
    assert "不替玩家说话或行动" in prompt
    assert "不编造未发生的情节" in prompt


def test_user_message_has_react_genre_and_keeps_routing_token():
    agent = CharacterAgent(
        CharacterSetting(name="杜甫", public_background="诗人"),
        ToolCallingLLM(),
        _FakeWorld(),
    )
    react = agent._build_user_message(
        "stage3", instruction="react", extra="玩家刚刚做出了行动：选择了一个行动「看看四周」。"
    )
    assert "【任务类型】react" in react
    assert "只写这个角色此刻说的一句话" in react
    assert "不要写旁白" in react

    propose = agent._build_user_message("stage3", instruction="propose_action")
    assert "【任务类型】propose_action" in propose
    assert "react" not in propose
