"""角色 Agent 流式链路测试（issue #59 / ADR-0005 §10、ADR-0004）。

三层：
1. `WenjingChatModel._astream`：可见文本与工具调用分片分道——分片是组装 tool_calls
   的原料，必须产出；但它**不是**可见文本，绝不混进台词。
2. LangChain agent 全链路：流式下工具节点照常触发，最终答复逐段可流。
3. `CharacterAgent.react_to(on_delta=...)`：增量即时回调，返回值仍是最终答复
   （工具轮的引导语是临时文本，不进返回值）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, HumanMessage

from app.contracts.enums import UsagePurpose
from app.domain.agents.character import CharacterAgent
from app.domain.agents.chat_model import WenjingChatModel
from app.domain.agents.tools import build_character_tools
from app.domain.game.types import CharacterSetting, PlayerAction
from app.domain.llm import LLMReply, StreamChunk, TokenUsage, ToolCallDelta
from tests.test_agent_tools import ToolCallingLLM, _FakeWorld, _Memory

PREAMBLE = "让我先查一下世界进度。"
FINAL = "我提议按进度推进。"


class _StreamingToolLLM:
    """脚本化流式 LLM：首轮先吐引导语再请求工具，工具回来后逐段吐最终答复。"""

    provider = "scripted"
    model = "scripted-1"

    def __init__(self, *, with_usage: bool = False) -> None:
        self.rounds: list[list[dict]] = []
        self.tool_rounds = 0
        self._with_usage = with_usage

    async def chat(self, messages, *, session_id: str = "", purpose=None) -> str:  # noqa: ANN001
        return FINAL

    async def astream(  # noqa: ANN201
        self, messages, *, session_id: str = "", purpose=None
    ) -> AsyncIterator[str]:
        yield FINAL

    async def chat_with_tools(  # noqa: ANN201
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> LLMReply:
        raise AssertionError("流式链路不得回落到非流式 chat_with_tools")

    async def astream_with_tools(  # noqa: ANN201
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> AsyncIterator[StreamChunk]:
        self.rounds.append(messages)
        has_tool_result = any(m.get("role") == "tool" for m in messages)
        if not has_tool_result:
            self.tool_rounds += 1
            yield StreamChunk(content=PREAMBLE)
            # 工具调用分片：首片带名字，后续片只带参数片段（真实 provider 的形状）
            yield StreamChunk(
                tool_calls=(ToolCallDelta(index=0, id="c1", name="view_world_progress"),)
            )
            yield StreamChunk(tool_calls=(ToolCallDelta(index=0, arguments="{}"),))
        else:
            for part in ("我提议", "按进度", "推进。"):
                yield StreamChunk(content=part)
        if self._with_usage:
            # 每次往返各报一次用量（ADR-0004 §4：一轮往返一条计量）
            yield StreamChunk(
                usage=TokenUsage(prompt_tokens=11, completion_tokens=7, total_tokens=18)
            )


def _tools() -> list[Any]:
    return build_character_tools(memory=_Memory(), world=_FakeWorld())


# ===== 1. ChatModel 适配层 =====


async def test_astream_keeps_tool_chunks_out_of_the_visible_channel():
    """工具调用分片只进工具通道，可见通道里只有台词。"""
    model = WenjingChatModel(service=_StreamingToolLLM()).bind_tools(_tools())

    chunks = [
        chunk async for chunk in model.astream([HumanMessage(content="提出行动")])
    ]

    text = "".join(chunk.content for chunk in chunks if isinstance(chunk.content, str))
    assert text == PREAMBLE
    assert "view_world_progress" not in text, "工具名不得出现在可见文本里"

    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert [c["name"] for c in merged.tool_calls] == ["view_world_progress"]
    assert merged.tool_calls[0]["args"] == {}, "参数分片应按 index 归并"


async def test_astream_carries_provider_usage_metadata():
    llm = _StreamingToolLLM(with_usage=True)
    model = WenjingChatModel(service=llm).bind_tools(_tools())
    chunks = [
        chunk async for chunk in model.astream([HumanMessage(content="提出行动")])
    ]
    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert merged.usage_metadata == {
        "input_tokens": 11,
        "output_tokens": 7,
        "total_tokens": 18,
    }


async def test_astream_degrades_to_single_chunk_without_streaming_capability():
    """内层没有 astream_with_tools：退回 `_agenerate` 单段产出，工具调用不丢。"""
    model = WenjingChatModel(service=ToolCallingLLM()).bind_tools(_tools())

    chunks = [
        chunk async for chunk in model.astream([HumanMessage(content="提出行动")])
    ]

    merged = chunks[0]
    for chunk in chunks[1:]:
        merged = merged + chunk
    assert [c["name"] for c in merged.tool_calls] == ["view_world_progress"]


# ===== 2. LangChain agent 全链路 =====


async def test_langchain_agent_streams_and_still_fires_the_tool_node():
    """流式不破坏 ADR-0004 的工具调用：工具节点照常执行，最终答复逐段可流。"""
    llm = _StreamingToolLLM()
    model = WenjingChatModel(service=llm)
    executor = create_agent(model, tools=_tools(), system_prompt="你是杜甫。")

    seen: list[str] = []
    async for chunk, _meta in executor.astream(
        {"messages": [HumanMessage(content="提出行动")]}, stream_mode="messages"
    ):
        if isinstance(chunk, AIMessageChunk) and isinstance(chunk.content, str):
            seen.append(chunk.content)

    assert llm.tool_rounds == 1, "工具节点应被触发一次"
    assert "stage" in str(llm.rounds[-1]).lower(), "模型应收到工具执行结果"
    assert "".join(seen).endswith(FINAL), "最终答复应逐段流出"
    assert FINAL in "".join(seen)


# ===== 3. CharacterAgent 层 =====


async def test_react_to_streams_deltas_and_returns_final_answer_only():
    llm = _StreamingToolLLM()
    agent = CharacterAgent(
        CharacterSetting(name="杜甫", public_background="诗人"), llm, _FakeWorld()
    )

    deltas: list[str] = []
    text = await agent.react_to(
        PlayerAction(type="text", text="我们去喝酒"),
        "stage2",
        on_delta=deltas.append,
    )

    assert text == FINAL, "返回值必须是最终答复，不含工具轮引导语"
    # 引导语是**临时**文本（ADR-0005 §10）：它允许被流出，由最终持久发言覆盖；
    # 最终答复则必须逐段回调，而不是等整段生成完再一次性给出。
    assert deltas == [PREAMBLE, "我提议", "按进度", "推进。"]
    assert agent.memory.working_memory[-1]["content"] == FINAL


async def test_react_to_without_sink_keeps_non_streaming_behaviour():
    """不给回调用回调：走 ainvoke 单轮，返回值与流式路径一致。"""
    llm = ToolCallingLLM()
    agent = CharacterAgent(
        CharacterSetting(name="杜甫", public_background="诗人"), llm, _FakeWorld()
    )

    text = await agent.react_to(PlayerAction(type="text", text="我们去喝酒"), "stage2")

    assert text == llm.final
    assert llm.tool_results, "非流式路径仍应经过工具调用"
