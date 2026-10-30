"""WS 瞬态流式协议端到端测试（issue #60 / ADR-0005 §10）。

三条验收：协议形状（start/delta/end，无 seq）、断线重连靠 resync 补全（不回放字幕）、
临时文本被最终持久发言覆盖。依赖真实 PG；不可用时沿用 `test_api_sessions` 的 client
fixture skip。
"""

from __future__ import annotations

import pytest

from tests.test_api_sessions import _full_setup
from tests.test_api_sessions import client as _sessions_client  # noqa: F401


@pytest.fixture(scope="module")
def ws_client(_sessions_client):  # noqa: F811 - 同名参数遮蔽上面的导入，pytest 按名字取夹具
    """复用 test_api_sessions 的装配（建库/注册/提权），只改个名字供本模块使用。"""
    return _sessions_client


def _submit(ws, sid: str, kind: str, payload: dict | None = None) -> None:
    ws.send_json(
        {
            "type": "submit_command",
            "command": {"session_id": sid, "kind": kind, "payload": payload or {}},
        }
    )


def _drain_until(ws, kind: str) -> list[dict]:
    msgs: list[dict] = []
    while True:
        msg = ws.receive_json()
        msgs.append(msg)
        if msg["type"] == kind:
            return msgs


def _to_stage2(client) -> str:  # noqa: ANN001
    sid, role = _full_setup(client)
    with client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()  # session_init
        _submit(ws, sid, "select_role", {"role_name": role})
        _drain_until(ws, "interaction")
    return sid


def _by_stream(streams: list[dict]) -> dict[str, list[dict]]:
    grouped: dict[str, list[dict]] = {}
    for message in streams:
        grouped.setdefault(message["payload"]["stream_id"], []).append(message)
    return grouped


def test_ws_streams_subtitles_then_persists_full_speech(ws_client):  # noqa: ANN001
    sid = _to_stage2(ws_client)

    with ws_client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()
        _submit(ws, sid, "choose_option", {"option_id": "0"})
        msgs = _drain_until(ws, "interaction")

    streams = [m for m in msgs if m["type"].startswith("stream_")]
    assert streams, "命令推进期间应有瞬态字幕流出"
    assert all("seq" not in m for m in streams), "瞬态消息不参与 seq"

    # 每条流 start → delta×N → end，且 stream_id 全局唯一
    grouped = _by_stream(streams)
    for stream_id, group in grouped.items():
        kinds = [m["type"] for m in group]
        assert kinds[0] == "stream_start" and kinds[-1] == "stream_end", stream_id
        assert "stream_delta" in kinds
    assert len(grouped) == len({m["payload"]["stream_id"] for m in streams})

    # 终态规则：持久 character_speech 在**所有**流收流之后到齐
    speech = [m for m in msgs if m["type"] == "character_speech"]
    assert speech, "角色发言必须落成持久事件"
    last_stream = max(i for i, m in enumerate(msgs) if m["type"].startswith("stream_"))
    first_speech = min(i for i, m in enumerate(msgs) if m["type"] == "character_speech")
    assert last_stream < first_speech, "持久发言必须在字幕收流之后下发"

    speakers = {m["payload"]["speaker"] for m in streams if m["type"] == "stream_start"}
    assert speakers == {m["payload"]["speaker"] for m in speech}, "每个发言角色都该有一条流"

    # 持久发言 = 该角色**流末**的最终文本。工具轮的引导语只活在流里，不落库
    # （ADR-0005 §10：临时文本由最终持久发言覆盖），所以这里用 endswith 而不是相等
    # ——真实 provider 是否先吐一段引导语不该决定这条协议的成败。
    for message in speech:
        stream_text = "".join(
            m["payload"]["text"]
            for m in streams
            if m["type"] == "stream_delta"
            and grouped[m["payload"]["stream_id"]][0]["payload"]["speaker"]
            == message["payload"]["speaker"]
        )
        assert stream_text.endswith(message["payload"]["text"]), "持久发言须是流末的最终文本"


def test_reconnect_does_not_replay_subtitles(ws_client):  # noqa: ANN001
    """断线重连：字幕不回放，完整文本由带 seq 的持久发言补上。"""
    sid = _to_stage2(ws_client)
    with ws_client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()
        _submit(ws, sid, "choose_option", {"option_id": "0"})
        msgs = _drain_until(ws, "interaction")

    expected = {m["payload"]["text"] for m in msgs if m["type"] == "character_speech"}
    assert expected

    with ws_client.websocket_connect(f"/ws/{sid}") as ws:
        init = ws.receive_json()
        assert init["type"] == "session_init"
        ws.send_json({"type": "resync_request", "last_confirmed_seq": 0})
        replayed: list[dict] = []
        while True:
            msg = ws.receive_json()
            replayed.append(msg)
            if msg["type"] == "interaction":
                break

    assert replayed, "resync 应补发缺口"
    assert all(not m["type"].startswith("stream_") for m in replayed), "字幕不入补发"
    assert all("seq" in m for m in replayed), "补发的都是持久消息"
    assert expected <= {
        m["payload"]["text"] for m in replayed if m["type"] == "character_speech"
    }, "完整发言由事件流补全"


def test_cancel_audio_is_accepted_and_does_not_disturb_the_command(ws_client):  # noqa: ANN001
    """barge-in（#62 / ADR-0005 §11）：打断只作用于音轨，不打断命令串行。

    客户端在命令前递一条 `cancel_audio`——它必须被当成合法帧（而不是
    `PROTOCOL_MALFORMED_MESSAGE`），随后的命令照常跑完、字幕照常收流；命令后再递
    一条也不能污染连接。音频出口是 M6（#63），今天没有音轨可取消，这条协议存在的
    意义正是"打断不许升级成抢占 LLM"。
    """
    sid = _to_stage2(ws_client)

    with ws_client.websocket_connect(f"/ws/{sid}") as ws:
        ws.receive_json()
        ws.send_json({"type": "cancel_audio", "track_id": "track-1"})
        _submit(ws, sid, "choose_option", {"option_id": "0"})
        msgs = _drain_until(ws, "interaction")

        assert not [m for m in msgs if m["type"] == "error"], "打断不该被当成畸形帧"
        assert [m for m in msgs if m["type"] == "character_speech"], "命令照常走完"

        # 命令之后再打断一次：连接仍然可用，服务端不回错误
        ws.send_json({"type": "cancel_audio", "track_id": "track-1"})
        ws.send_json({"type": "resync_request", "last_confirmed_seq": 0})
        assert ws.receive_json()["type"] == "character_speech"
