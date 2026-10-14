# ===== 驳回回灌：revise_proposal 真实重新提案 =====

from app.domain.game.game_runtime import GameRuntime
from app.domain.game.types import Beat, CharacterSetting, Scene, Script


class _ReviseProbeLLM:
    """可控 LLM：首次提议返回会被驳回的文本，revise 轮返回调整后的新文本。

    记下每次收到的 user 消息，断言驳回理由确实回灌进了 prompt。
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def chat(self, messages, *, session_id: str = "", purpose=None):
        joined = " ".join(
            m["content"] if isinstance(m.get("content"), str) else "" for m in messages
        )
        self.calls.append(joined)
        if "验证 Agent" in joined:
            # 按提议文本判定；revise 轮文本也是「验证 Agent」调用，须区分轮次
            return "reject" if "proposal=原提议" in joined else "pass"
        if "已被驳回" in joined:
            return "调整后的新提议"
        return "原提议"


async def test_revise_proposal_feeds_rejection_back_and_updates_proposal(engine_config):
    """驳回理由要回灌 LLM，修订提议是新的真实描述而非模板串。

    minimal_script 只有 1 个 stage2 beat，选角后立刻到终点确认交互点；
    这里造一个 2-beat 剧本让首轮交互点是选项列表，修订提议才能进事件流。
    """
    script = Script(
        title="修订测试剧本",
        characters=[
            CharacterSetting(name="李白", public_background="诗人", is_player_playable=True),
            CharacterSetting(name="杜甫", public_background="另一位诗人"),
        ],
        scenes=[
            Scene(
                scene_id=1,
                title="相遇",
                participants=["李白", "杜甫"],
                beats=[
                    Beat(beat_id=1, description="相遇"),
                    Beat(beat_id=2, description="同游"),
                ],
            )
        ],
        stage2_ending_beat_id=2,
    )
    llm = _ReviseProbeLLM()
    rt = GameRuntime(
        session_id="rt-revise",
        script=script,
        llm=llm,
        config=engine_config,
    )
    await rt.start()
    await rt.submit(command_id="rev-sel", kind="select_role", payload={"role_name": "李白"})
    assert any("已被驳回" in c for c in llm.calls), "驳回理由未回灌"
    assert any("原提议是" in c for c in llm.calls), "原提议未回灌"
    # 修订提议不发 proposal 事件（事件只记首轮收集），进的是收录后的选项
    assert any(p.description == "调整后的新提议" for p in rt._valid_proposals), "修订提议未收录"
