"""pytest 共享夹具：FakeLLMService + 最小集剧本 + 引擎工厂。

本 MVP 阶段聚焦引擎机制（不测剧情质量、不测剧本生成链路），
因此：
- `FakeLLMService` 返回预设确定性输出（默认 pass，可配置 reject）
- `minimal_script` 是写死的最小集（1 主角 + 2 配角 + 3 beat）
- `make_engine` 工厂快速构造引擎实例
"""

from __future__ import annotations

import pytest

from app.core.engine_config import EngineConfig
from app.core.game_engine import GameEngine
from app.core.types import Beat, CharacterSetting, Scene, Script


class FakeLLMService:
    """确定性 LLM 假实现：按调用上游分类返回预设输出。"""

    def __init__(
        self,
        *,
        proposal_text: str = "我提议质询对方",
        react_text: str = "我平静地回应。",
        verifier_output: str = "pass",
    ) -> None:
        self._proposal_text = proposal_text
        self._react_text = react_text
        self._verifier_output = verifier_output
        self.call_count = 0
        self.calls: list[list[dict]] = []

    async def chat(self, messages, *, session_id: str = ""):
        self.call_count += 1
        self.calls.append(messages)
        user = messages[-1]["content"] if messages else ""
        if "验证 Agent" in user or "你是验证" in user:
            return self._verifier_output
        if "react" in user:
            return self._react_text
        return self._proposal_text


@pytest.fixture
def fake_llm():
    return FakeLLMService()


@pytest.fixture
def minimal_script() -> Script:
    """最小集剧本：1 主角（玩家）+ 2 配角 + 2 场景共 3 beat。"""
    return Script(
        title="最小集测试剧本",
        characters=[
            CharacterSetting(
                name="李白",
                public_background="诗人，豪放不羁",
                personality_traits=["豪放", "重情"],
                is_player_playable=True,
            ),
            CharacterSetting(name="杜甫", public_background="另一位诗人"),
            CharacterSetting(name="高适", public_background="边塞诗人"),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="相遇",
                participants=["李白", "杜甫", "高适"],
                beats=[
                    Beat(beat_id=1, description="三人在长安酒馆相遇"),
                    Beat(beat_id=2, description="杜甫提出游览山水"),
                ],
            ),
            Scene(
                scene_id=2,
                title="送别",
                participants=["李白", "高适"],
                beats=[Beat(beat_id=3, description="高适出发赴边塞，李白送别")],
            ),
        ],
        stage2_ending_beat_id=3,
    )


@pytest.fixture
def engine_config() -> EngineConfig:
    return EngineConfig(stage3_rounds=2)


@pytest.fixture
def make_engine(minimal_script, fake_llm, engine_config):
    def _make(session_id: str = "test-session") -> GameEngine:
        return GameEngine(
            session_id=session_id,
            script=minimal_script,
            llm=fake_llm,
            config=engine_config,
            enable_logging=False,
        )

    return _make
