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
from app.domain.agents.character import CharacterAgent, _final_text
from app.domain.agents.chat_model import WenjingChatModel
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
