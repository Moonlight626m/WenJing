"""pytest 共享夹具：FakeLLMService + 最小集剧本 + 运行时工厂。

机制测试（不测剧情质量、不测剧本生成链路）：
- `FakeLLMService` 返回预设确定性输出（默认 pass，可配置 reject）
- `minimal_script` 是写死的最小集（1 主角 + 2 配角 + 3 beat）
- `make_runtime` 工厂构造 command/step 运行时实例
"""

from __future__ import annotations

import pytest

from app.core.engine_config import EngineConfig
from app.core.game_runtime import GameRuntime
from app.core.types import Beat, CharacterSetting, Scene, Script


async def reset_baseline_schema(conn) -> None:
    """DB 集成测试清场：drop_all/create_all 并同步移除 alembic_version。

    只 drop_all 不动 alembic_version 会留下"版本戳在、表已清"的脏状态，
    后续 alembic upgrade head 变 no-op，迁移测试必炸（自愈缺口）。
    """
    from sqlalchemy import text

    from app.db.session import Base

    await conn.run_sync(Base.metadata.drop_all)
    await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))
    await conn.run_sync(Base.metadata.create_all)


async def create_actor(
    factory, *, name: str = "测试学校", role: str = "teacher"
):
    """建一个 org + user 并返回其领域身份（#18 会话归属用）。"""
    import uuid as _uuid

    from app.access import Actor
    from app.contracts.enums import UserRole
    from app.models.org import Org
    from app.models.user import User

    async with factory() as s:
        org = Org(name=f"{name}-{_uuid.uuid4().hex[:8]}")
        s.add(org)
        await s.flush()
        uid = _uuid.uuid4()
        user = User(
            id=uid,
            org_id=org.id,
            role=role,
            email=f"{uid}@test.local",
            nickname="测试用户",
            password_hash="unused",
        )
        s.add(user)
        await s.flush()
        await s.commit()
        return Actor(user_id=user.id, org_id=org.id, role=UserRole(role))


async def drop_baseline_schema(conn) -> None:
    """测试后清场：连同 alembic_version 一起移除，交还干净库。"""
    from sqlalchemy import text

    from app.db.session import Base

    await conn.run_sync(Base.metadata.drop_all)
    await conn.execute(text("DROP TABLE IF EXISTS alembic_version"))


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
def make_runtime(minimal_script, fake_llm, engine_config):
    def _make(session_id: str = "test-session") -> GameRuntime:
        return GameRuntime(
            session_id=session_id,
            script=minimal_script,
            llm=fake_llm,
            config=engine_config,
            enable_logging=False,
        )

    return _make


def _is_ending_confirm(result_active_interaction: dict | None) -> bool:
    """结局确认交互点：由 system 提议的选项。"""
    if not result_active_interaction:
        return False
    return any(o.get("proposed_by") == "system" for o in result_active_interaction["options"])


async def play_until_terminal(rt: GameRuntime, *, end_at_ending: bool = False):
    """命令序列驱动器：自动选角并按阶段提交合法命令直到终态。"""
    counter = {"n": 0}

    async def send(kind: str, payload: dict | None = None):
        counter["n"] += 1
        return await rt.submit(
            command_id=f"cmd-{counter['n']}", kind=kind, payload=payload or {}
        )

    result = await rt.start()
    assert result.state["stage"] in ("stage1_complete",)

    while True:
        if result.terminal:
            return result
        stage = result.state["stage"]
        if stage == "stage1_complete":
            result = await send("select_role", {"role_name": "李白"})
        elif stage == "stage2_reenacting":
            if result.active_interaction is None:
                raise AssertionError("stage2 中必须有活动交互点")
            if _is_ending_confirm(result.active_interaction):
                choice = 1 if end_at_ending else 0
                result = await send(
                    "choose_option", {"option_id": str(choice)}
                )
            else:
                result = await send("choose_option", {"option_id": "0"})
        elif stage == "stage2_complete":
            result = await send("enter_stage3")
        elif stage == "stage3_extending":
            result = await send("choose_option", {"option_id": "0"})
        else:
            raise AssertionError(f"非预期阶段 {stage}")
