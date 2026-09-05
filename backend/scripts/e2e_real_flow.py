"""真实核心集成端到端驱动（issue #12 验收脚本）。

对运行中的后端驱动完整核心流程（fake 或真实 LLM 均可，自动检测）：
导入课文 → Stage1 生成（真实链路含 4-8 次 LLM 调用，可能 1-2 分钟）→
选角 → Stage2 推进至课文结局 → 进入 Stage3（自由输入 + 选项）→
回溯分支 → 重连恢复 → 退出（terminal）→ 终局后命令报错（envelope 校验）。

前置：
    make db-up && make migrate
    make dev-backend            # 快速模式：WENJING_LLM_API_KEY= uv run uvicorn ...

用法：
    cd backend && uv run python scripts/e2e_real_flow.py [BASE_URL]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

import httpx
import websockets

DEFAULT_BASE = "http://localhost:8000"
DEFAULT_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
    "我守在母亲的床边，一夜没合眼。天亮时，她握住我的手说：去吧。"
)

MAX_STAGE2_ROUNDS = 40
CMD_TIMEOUT = 240.0  # 真实 LLM 下单命令可能数十秒


def _step(title: str) -> None:
    print(f"\n=== {title} ===", flush=True)


def _dump(obj) -> str:
    return json.dumps(obj, ensure_ascii=False)


def _json(raw) -> dict:
    return json.loads(raw)


def _text(msg: dict) -> str:
    p = msg.get("payload", {})
    if msg["type"] == "interaction":
        ix = p.get("interaction", {})
        opts = " / ".join(o["label"][:24] for o in ix.get("options", []))
        return f"{ix.get('prompt', '')[:50]} 选项：{opts}"
    return str(p.get("text", ""))[:70]


async def _drain_until_interaction(ws) -> list[dict]:
    """读取消息直到出现交互点（或终局文本）。"""
    msgs = []
    while True:
        msg = _json(await asyncio.wait_for(ws.recv(), timeout=CMD_TIMEOUT))
        if msg["type"] == "error":
            raise SystemExit(f"服务端错误：{msg['payload']['code']} {msg['payload']['message']}")
        msgs.append(msg)
        if msg["type"] == "interaction":
            return msgs
        if msg["type"] == "system" and "已结束" in _text(msg):
            return msgs


async def main() -> int:
    parser = argparse.ArgumentParser(description="文境 #12 真实集成端到端")
    parser.add_argument("base", nargs="?", default=DEFAULT_BASE)
    parser.add_argument("--text-file", default=None, help="课文文本文件路径")
    args = parser.parse_args()
    base = args.base.rstrip("/")
    text = open(args.text_file, encoding="utf-8").read() if args.text_file else DEFAULT_TEXT

    sid = ""
    async with httpx.AsyncClient(base_url=base, timeout=CMD_TIMEOUT) as http:
        _step("1. 创建会话 + 导入课文（真实 ingestion + 原文分析）")
        sid = (await http.post("/api/sessions")).json()["session_id"]
        resp = await http.post(
            f"/api/sessions/{sid}/material", json={"source": "paste", "raw_text": text}
        )
        if resp.status_code != 200:
            print("导入失败：", resp.text)
            return 1
        analysis = resp.json()
        print(
            "分析：", analysis["genre"]["genre"],
            "| 人物", [c["name"] for c in analysis["characters"]],
            "| 关键事件", len(analysis["key_events"]),
        )

        _step("2. Stage1 生成（真实 LLM 时 1-2 分钟）")
        resp = await http.post(f"/api/sessions/{sid}/generate")
        if resp.status_code != 200:
            print("生成失败：", resp.text)
            return 1
        pkg = resp.json()
        print(
            "剧本：", pkg["title"],
            "| 角色", [c["name"] for c in pkg["characters"]],
            "| 可扮演", pkg["playable_roles"],
        )
        status = (await http.get(f"/api/sessions/{sid}")).json()
        if status.get("generation"):
            print("生成进度：", {p["name"]: p["state"] for p in status["generation"]["phases"]})

        ws_url = base.replace("http", "ws", 1) + f"/ws/{sid}"
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            _json(await asyncio.wait_for(ws.recv(), timeout=30))  # session_init

            _step("3. 选角 → Stage2（模式 A：options）")
            role = pkg["playable_roles"][0]
            await ws.send(_dump({"type": "submit_command", "command": {
                "command_id": str(uuid.uuid4()), "session_id": sid,
                "kind": "select_role", "payload": {"role_name": role}}}))
            msgs = await _drain_until_interaction(ws)
            print("选角消息：", [f"[{m['seq']}]{m['type']}" for m in msgs])
            ix = next(m for m in msgs if m["type"] == "interaction")["payload"]
            assert ix["interaction"]["mode"] == "options", "Stage2 应为 options 模式"

            _step("4. Stage2 推进至课文结局（确认点）")
            for round_no in range(MAX_STAGE2_ROUNDS):
                await ws.send(_dump({"type": "submit_command", "command": {
                    "command_id": str(uuid.uuid4()), "session_id": sid,
                    "kind": "choose_option", "payload": {"option_id": "0"}}}))
                msgs = await _drain_until_interaction(ws)
                ix = next(m for m in msgs if m["type"] == "interaction")["payload"]["interaction"]
                if "结局" in ix["prompt"]:
                    break
            else:
                raise SystemExit("未到达结局确认点")
            print(f"到达结局确认（{round_no + 1} 轮推进）")

            _step("5. 选择续写 → stage2_complete → enter_stage3（模式 C）")
            # 结局选择 0 → stage2_complete（仅阶段切换消息，无交互点）；
            # 服务端命令按序处理，连发 enter_stage3 后 drain 到 Stage3 首个交互点
            await ws.send(_dump({"type": "submit_command", "command": {
                "command_id": str(uuid.uuid4()), "session_id": sid,
                "kind": "choose_option", "payload": {"option_id": "0"}}}))
            await ws.send(_dump({"type": "submit_command", "command": {
                "command_id": str(uuid.uuid4()), "session_id": sid,
                "kind": "enter_stage3", "payload": {}}}))
            msgs = await _drain_until_interaction(ws)
            ix = next(m for m in msgs if m["type"] == "interaction")["payload"]
            mode = ix["interaction"]["mode"]
            assert mode == "options_with_fallback", f"Stage3 应为模式 C：{mode}"
            print("阶段消息：", [f"[{m['seq']}]{m['type']}" for m in msgs])

            _step("6. Stage3 自由输入（模式 B）+ 回溯分支")
            await ws.send(_dump({"type": "submit_command", "command": {
                "command_id": str(uuid.uuid4()), "session_id": sid,
                "kind": "free_input", "payload": {"text": "我想先回家看看母亲"}}}))
            msgs = await _drain_until_interaction(ws)
            print("自由输入后：", [f"[{m['seq']}]{m['type']}" for m in msgs][-3:])

            target = max(1, msgs[-1]["seq"] - 4)
            await ws.send(_dump({"type": "submit_command", "command": {
                "command_id": str(uuid.uuid4()), "session_id": sid,
                "kind": "rollback_to_event", "payload": {"target_sequence": target}}}))
            msgs = await _drain_until_interaction(ws)
            rollback_msg = next(
                (m for m in msgs if m["type"] == "system" and "回溯" in _text(m)), None
            )
            assert rollback_msg is not None, "应包含回溯系统消息"
            print("回溯消息：", _text(rollback_msg))

            _step("7. 退出游戏（terminal）+ 终局后命令报错校验")
            await ws.send(_dump({"type": "submit_command", "command": {
                "command_id": str(uuid.uuid4()), "session_id": sid,
                "kind": "exit_game", "payload": {}}}))
            msgs = await _drain_until_interaction(ws)
            print("终局批次：", [(m["seq"], m["type"], _text(m)[:30]) for m in msgs])
            assert any("已结束" in _text(m) for m in msgs), "应有终局消息"
            print("终局消息：", [_text(m) for m in msgs if m["type"] == "system"][-1:])

            await ws.send(_dump({"type": "submit_command", "command": {
                "command_id": str(uuid.uuid4()), "session_id": sid,
                "kind": "exit_game", "payload": {}}}))
            err = _json(await asyncio.wait_for(ws.recv(), timeout=30))
            assert err["type"] == "error", f"终局后命令应报错：{err['type']}"
            p = err["payload"]
            assert p["code"] == "SESSION_ENDED" and p["domain"] == "session", p
            assert p["error_id"], "error_id 必须存在"
            print("终局后错误 envelope ✓", p["code"], "| error_id:", p["error_id"])

    _step("演示完成 ✓")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
