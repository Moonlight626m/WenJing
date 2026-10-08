"""角色 Agent 的 LangChain 工具集：把"查看世界进度"等能力封装成可调用工具。

设计（ADR-0004）：
- 角色 Agent 不再被动接收引擎广播的剧情上下文，而是通过工具**按需查询**当前
  世界状态（阶段/进度、剧情日志、当前矛盾、剧本大纲、在场角色、自身记忆）。
- `WorldView` 是 agent 侧只读端口，真实实现（`RuntimeWorldView`）由游戏引擎提供；
  agent 只依赖端口，保持 domain 内分层解耦与可测试性。
- 工具用 `@tool` 声明，返回 JSON 文本（对模型友好、可直接引用字段）。
"""

from __future__ import annotations

import json
from typing import Any, Protocol, runtime_checkable

from langchain_core.tools import BaseTool, tool


@runtime_checkable
class WorldView(Protocol):
    """角色 Agent 可见的世界只读视图（由游戏引擎实现）。"""

    def progress(self) -> dict[str, Any]:
        """当前世界进度：stage / phase / beat_cursor / total_beats / player_role / ended。"""

    def plot_log(self, limit: int = 5) -> list[str]:
        """最近的剧情推进摘要（时间正序）。"""

    def direction(self) -> dict[str, str]:
        """当前矛盾与关键处境（conflict / context）。"""

    def outline(self) -> list[dict[str, Any]]:
        """剧本大纲：每个场景的标题、参与角色与情节点。"""

    def roster(self) -> list[dict[str, Any]]:
        """在场角色名册：名字、公开背景、是否为玩家角色。"""


class MemoryView(Protocol):
    """角色自身记忆的只读投影（`CharacterMemory` 结构上满足）。"""

    personal_log: list[str]
    rejected: list[str]


def build_character_tools(
    *, memory: MemoryView, world: WorldView
) -> list[BaseTool]:
    """为单个角色构造工具集（闭包捕获该角色的记忆与共享世界视图）。"""

    @tool
    def view_world_progress() -> str:
        """查看当前世界进度：所处阶段、剧情节拍进度、玩家扮演角色、是否已到终局。"""
        return _dump(world.progress())

    @tool
    def view_plot_log() -> str:
        """查看最近发生的剧情推进摘要，了解故事进行到哪一步。"""
        return _dump(world.plot_log())

    @tool
    def view_current_direction() -> str:
        """查看当前的核心矛盾与关键处境，作为本轮行动的依据。"""
        return _dump(world.direction())

    @tool
    def view_story_outline() -> str:
        """查看剧本场景大纲与情节点，了解课文原情节走向。"""
        return _dump(world.outline())

    @tool
    def view_characters() -> str:
        """查看登场角色名册与各自的公开背景。"""
        return _dump(world.roster())

    @tool
    def view_my_memory() -> str:
        """查看你自己的私有记忆：先前提议与自我行动日志。"""
        return _dump(
            {"personal_log": memory.personal_log[-10:], "rejected": memory.rejected[-10:]}
        )

    return [
        view_world_progress,
        view_plot_log,
        view_current_direction,
        view_story_outline,
        view_characters,
        view_my_memory,
    ]


def _dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)
