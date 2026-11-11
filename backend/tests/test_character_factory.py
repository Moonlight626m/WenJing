"""角色模板 / 工厂：模板投影、实例隔离、与运行时注册表的接线。"""

from __future__ import annotations

from typing import Any

from app.contracts.enums import UsagePurpose
from app.domain.agents.character import (
    CharacterAgentManager,
    CharacterFactory,
    CharacterTemplate,
)
from app.domain.game.types import CharacterSetting
from app.domain.llm import LLMReply


class _StubLLM:
    async def chat(self, messages, *, session_id: str = "", purpose=None) -> str:
        return ""

    async def chat_with_tools(
        self,
        messages: list[dict],
        *,
        tools: list[dict] | None = None,
        session_id: str = "",
        purpose: UsagePurpose = UsagePurpose.AGENT,
    ) -> LLMReply:
        return LLMReply(content="")


class _FakeWorld:
    def progress(self) -> dict[str, Any]:
        return {}

    def plot_log(self, limit: int = 5) -> list[str]:
        return []

    def direction(self) -> dict[str, str]:
        return {}

    def outline(self) -> list[dict[str, Any]]:
        return []

    def roster(self) -> list[dict[str, Any]]:
        return []

    def chronicle(self) -> str:
        return ""

    def bind(self, viewer: str) -> _FakeWorld:
        return self


def test_template_to_setting_drops_not_knows():
    setting = CharacterSetting(
        name="闰土",
        public_background="海边少年",
        personality_traits=["机敏", "腼腆"],
        speech_style="短句，带乡音",
        knows=["雪地捕鸟的诀窍"],
        not_knows=["成年后的窘迫"],
        is_player_playable=True,
    )
    template = CharacterTemplate.from_setting(setting)
    assert template.knowledge_seeds == ("雪地捕鸟的诀窍",)
    assert template.playable is True

    restored = template.to_setting()
    assert restored.name == "闰土"
    assert restored.personality_traits == ["机敏", "腼腆"]
    assert restored.knows == ["雪地捕鸟的诀窍"]
    assert restored.not_knows == []
    assert restored.is_player_playable is True


def test_factory_instances_do_not_share_memory():
    factory = CharacterFactory(_StubLLM())
    template = CharacterTemplate(name="闰土", public_background="海边少年")
    world = _FakeWorld()

    first = factory.create(template, world=world)
    second = factory.create(template, world=world)
    first.record_speech("第一局的闰土说")

    assert first is not second
    assert first.memory is not second.memory
    assert second.memory.working_memory == []


def test_manager_creates_agents_through_factory():
    manager = CharacterAgentManager(_StubLLM(), _FakeWorld())
    manager.create_agents(
        [
            CharacterSetting(name="闰土", public_background="海边少年"),
            CharacterSetting(
                name="我",
                public_background="回乡的少爷",
                is_player_playable=True,
            ),
        ]
    )

    assert set(manager.agents) == {"闰土", "我"}
    assert isinstance(manager.factory, CharacterFactory)
    assert manager.player_role == "我"
    assert manager.agents["闰土"].memory is not manager.agents["我"].memory
