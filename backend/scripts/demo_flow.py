"""文境核心流程演示脚本（issue #5 验收）。

对运行中的后端完整演示：创建会话 → 导入课文 → 生成剧本 → WS 选角 →
命令推进 → 回溯 → 重连恢复（session_init 重建 + resync 补发）。

前置：
    make db-up && make migrate
    make dev-backend            # 或 uvicorn app.main:app --port 8000

说明：
- 服务端 .env 配有真实 LLM key 时，命令推进含真实 LLM 调用（每个角色提议/反应
  一次调用，可能数十秒）；演示客户端已禁用 WS keepalive 以等待长耗时步骤。
- 快速模式（确定性假 LLM，秒级）：
    WENJING_LLM_API_KEY= uv run uvicorn app.main:app --port 8000

用法：
    cd backend && uv run python scripts/demo_flow.py [BASE_URL]

课文内容可用 --text-file 指定（默认内置叙事样例）。
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import httpx
import websockets

DEFAULT_BASE = "http://localhost:8000"
DEFAULT_TEXT = (
    "那年冬天，母亲病了。我离开家，到城里去买药。"
    "母亲说：路上小心。我回头看见她站在门口，眼泪流了下来。"
)


def _step(title: str) -> None:
    print(f"\n=== {title} ===")


def _cmd(sid: str, kind: str, payload: dict) -> str:
    return _dump(
        {
            "type": "submit_command",
            "command": {"session_id": sid, "kind": kind, "payload": payload},
        }
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="文境核心流程演示")
    parser.add_argument("base", nargs="?", default=DEFAULT_BASE)
    parser.add_argument("--text-file", default=None, help="课文文本文件路径")
    args = parser.parse_args()
    base = args.base.rstrip("/")

    text = DEFAULT_TEXT
    if args.text_file:
        text = Path(args.text_file).read_text(encoding="utf-8")

    async with httpx.AsyncClient(base_url=base, timeout=60) as http:
        _step("1. 创建会话")
        sid = (await http.post("/api/sessions")).json()["session_id"]
        print(f"session_id = {sid}")

        _step("2. 导入课文（真实 ingestion + 原文分析）")
        resp = await http.post(
            f"/api/sessions/{sid}/material",
            json={"source": "paste", "raw_text": text},
        )
        if resp.status_code != 200:
            print("导入失败：", resp.text)
            return 1
        analysis = resp.json()
        print("人物：", [c["name"] for c in analysis["characters"]])

        _step("3. 生成剧本（fake-backed 确定性合成）")
        resp = await http.post(f"/api/sessions/{sid}/generate")
        if resp.status_code != 200:
            print("生成失败：", resp.text)
            return 1
        pkg = resp.json()
        print(
            "剧本：", pkg["title"],
            "| 可扮演角色：", pkg["playable_roles"],
            "| 关键 beat：", sum(len(s["beats"]) for s in pkg["scenes"]),
        )

        ws_url = base.replace("http", "ws", 1) + f"/ws/{sid}"
        last_confirmed = 0
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            _step("4. WS 连接 → session_init")
            init = _json(await ws.recv())
            print(
                "阶段：", init["payload"]["stage"],
                "| 可用命令：", init["payload"]["allowed_commands"],
            )

            _step("5. 选角并推进交互点（先提交后读消息，避免遗留）")
            role = pkg["playable_roles"][0]
            await ws.send(_cmd(sid, "select_role", {"role_name": role}))
            for m in await _drain_until_interaction(ws):
                print(f"[{m['seq']:>3}] {m['type']:<17} {_text(m)}")
                last_confirmed = max(last_confirmed, m["seq"])
            await ws.send(_dump({"type": "confirm_messages", "last_confirmed_seq": last_confirmed}))

            await ws.send(_cmd(sid, "choose_option", {"option_id": "0"}))
            for m in await _drain_until_interaction(ws):
                print(f"[{m['seq']:>3}] {m['type']:<17} {_text(m)}")
                last_confirmed = max(last_confirmed, m["seq"])

            _step("6. 回溯（保留旧历史，新分支重推进）")
            target = max(1, last_confirmed - 6)
            await ws.send(
                _cmd(sid, "rollback_to_event", {"target_sequence": target})
            )
            for m in await _drain_until_interaction(ws):
                print(f"[{m['seq']:>3}] {m['type']:<17} {_text(m)}")

        _step("7. 断线重连：session_init 从 DB 重建 + resync 补发")
        async with websockets.connect(ws_url, ping_interval=None) as ws:
            init = _json(await ws.recv())
            print(
                "重建阶段：", init["payload"]["stage"],
                "| player：", init["payload"].get("player_role"),
            )
            await ws.send(_dump({"type": "resync_request", "last_confirmed_seq": 0}))
            replayed = _json(await ws.recv())
            print(f"resync 首条补发：[{replayed['seq']}] {replayed['type']}")

    _step("演示完成")
    return 0


async def _drain_until_interaction(ws) -> list:
    msgs = []
    while True:
        msg = _json(await ws.recv())
        if msg["type"] == "error":
            print("错误：", msg["payload"]["message"])
            raise SystemExit(1)
        msgs.append(msg)
        if msg["type"] in ("interaction",) or (
            msg["type"] == "system" and "已结束" in _text(msg)
        ):
            return msgs


def _text(msg) -> str:
    p = msg.get("payload", {})
    if msg["type"] == "interaction":
        ix = p.get("interaction", {})
        opts = " / ".join(o["label"][:20] for o in ix.get("options", []))
        return f"{ix.get('prompt', '')[:40]} 选项：{opts}"
    return str(p.get("text", ""))[:60]


def _dump(obj) -> str:
    import json

    return json.dumps(obj, ensure_ascii=False)


def _json(raw) -> dict:
    import json

    return json.loads(raw)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
