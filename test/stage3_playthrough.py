#!/usr/bin/env python3
"""Stage3 自由探索试运行客户端（黑盒模拟用户）。

对已经跑起来的后端走**真实协议**：登录（Cookie + CSRF）→ 从已发布剧本开局 →
WS 选角 → Stage2 选项播放到课文结局 → enter_stage3 → **命令行交互推进**。
每一步的 WS 消息、命令、交互点、阶段变化都落到 `test/runs/<时间戳>/`。

默认是命令行交互：每轮先打印「角色发言和行为」「场景/故事更新」，再给出
选项和输入提示，玩家输入序号选择，或直接输入文字自由发言（Stage3）；
`--auto` 退回脚本化自动推进（原试运行模式）。

它不 import 任何 `app.*` 模块，只依赖 httpx/websockets，所以既能验证协议，
也能用来实际玩一段自由探索。

用法（在 backend 目录下跑，复用后端的 venv）：
    cd backend && uv run python ../test/stage3_playthrough.py            # 交互式
    cd backend && uv run python ../test/stage3_playthrough.py --auto     # 自动 8 轮
    cd backend && uv run python ../test/stage3_playthrough.py --keep-open # 退出时不关局

交互命令：
    序号        选择对应选项
    直接文字     自由发言（Stage3）
    /s          列出可前往的地点；/s N 前往第 N 个
    /i 文字      干涉世界（建场景/拉入角色，由 WorldBuilderAgent 解析）
    /m          重新显示当前交互点
    /h          帮助
    /q          退出本局

产物：
    test/runs/<ts>/ws_messages.jsonl   双向 WS 消息（含 stream_* / audio_*）
    test/runs/<ts>/transcript.md       人读的剧情进程（叙事/台词/交互点/命令）
    test/runs/<ts>/timeline.json       活动分支事件时间线（GET /timeline）
    test/runs/<ts>/instance_events.jsonl  fs 实例目录的事件镜像
    test/runs/<ts>/summary.json        会话 ID、turn 统计、阶段、耗时、实例目录
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import websockets

DEFAULT_BASE = "http://localhost:8000"
DEFAULT_IDENTIFIER = "student"
DEFAULT_PASSWORD = "123456"
DEFAULT_SCRIPT_ID = 1

# 模拟用户：Stage3 的自由输入（背影语境）。按顺序轮换，保证可复现。
FREE_INPUTS = [
    "我走到父亲身边，想接过他手里的朱红橘子。",
    "我轻声问父亲：爹，您路上要不要歇一歇？",
    "我望向月台尽头，想看看还有没有别的亲人来送行。",
    "我低头整理衣角，心里想着刚才没能说出口的话。",
    "我扶着父亲的胳膊，慢慢向车厢门口走去。",
    "我回头又望了一眼站台，想把这一刻记在心里。",
    "我在父亲身边坐下，问他路上冷不冷。",
    "我想起母亲说过的话，鼻子忽然有些发酸。",
]

# 模拟用户：偶尔用 intervene 让 WorldBuilderAgent 解析建场景/拉角色。
INTERVENTIONS = [
    "让旁边那位挑担的老先生也走过来，和父亲搭两句话。",
    "在月台边上摆一个卖热茶的小摊，让来往的旅人歇歇脚。",
]

TURN_MARK = "──────────────"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _msg_text(msg: dict[str, Any]) -> str:
    p = msg.get("payload") or {}
    t = msg.get("type", "")
    if t == "narrative":
        return p.get("text", "")
    if t == "character_speech":
        return f'{p.get("speaker", "?")}：{p.get("text", "")}'
    if t == "system":
        return p.get("text", "")
    if t == "interaction":
        ix = p.get("interaction") or {}
        opts = " / ".join(
            f'[{o.get("option_id")}]{o.get("label", "")[:28]}'
            for o in ix.get("options", [])
        )
        scenes = " / ".join(
            f'{s.get("scene_key")}({s.get("title", "")})'
            for s in ix.get("scene_options", [])
        )
        parts = [f'交互点 {ix.get("interaction_id")} mode={ix.get("mode")}',
                 f'提示：{_short(ix.get("prompt", ""))}']
        if opts:
            parts.append(f"选项：{opts}")
        if scenes:
            parts.append(f"可换景：{scenes}")
        return " | ".join(parts)
    if t == "asset_ready":
        return f'配图就绪：{p.get("asset_id", "")}'
    return ""


HELP_TEXT = """\
交互命令：
  序号        选择对应选项
  直接文字     自由发言（Stage3；Stage2 只接受序号）
  /s          列出可前往的地点；/s N 前往第 N 个
  /i 文字      干涉世界（建场景/拉入角色，由 WorldBuilderAgent 解析）
  /m          重新显示当前交互点
  /h          帮助
  /q          退出本局"""


def _payload(msg: dict[str, Any]) -> dict[str, Any]:
    return msg.get("payload") or {}


def _is_character_behavior(msg: dict[str, Any]) -> bool:
    """角色台词与「父亲 提议：（…）」都算角色的发言/行为。"""
    if msg.get("type") == "character_speech":
        return True
    return msg.get("type") == "system" and " 提议：" in _payload(msg).get("text", "")


def render_batch(batch: list[dict[str, Any]]) -> None:
    """按「角色发言 → 场景/故事更新」两段式渲染一批消息。"""
    speeches = [m for m in batch if _is_character_behavior(m)]
    updates = [
        m
        for m in batch
        if m.get("type") in ("narrative", "system")
        and not _is_character_behavior(m)
    ]
    if speeches:
        print("\n==角色发言和行为==")
        for msg in speeches:
            p = _payload(msg)
            if msg.get("type") == "character_speech":
                print(f'{p.get("speaker", "?")}：{p.get("text", "")}')
            else:
                print(p.get("text", ""))
    if updates:
        print("\n==场景/故事更新==")
        for msg in updates:
            text = _payload(msg).get("text", "")
            if text.startswith("你来到了"):
                # narrative：你来到了「车厢内外：我的自以为是」（在场：我、父亲）
                text = f"【进入新场景：{text[4:]}】"
            print(text)


def _other_scenes(ix: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        s
        for s in (ix.get("scene_options") or [])
        if not s.get("is_current")
    ]


def render_interaction(ix: dict[str, Any]) -> None:
    prompt = (ix.get("prompt") or "").strip()
    if prompt:
        print(f"\n（{_short(prompt, 200)}）")
    options = ix.get("options") or []
    print("\n==请选择你的行为==")
    for index, option in enumerate(options, 1):
        print(f'  {index}. {option.get("label", "")}')
    scenes = _other_scenes(ix)
    if scenes:
        listing = "；".join(
            f'/s {i}={s.get("title", "")}' for i, s in enumerate(scenes, 1)
        )
        print(f"可前往：{listing}")
    if ix.get("mode") == "options":
        print("输入序号选择（/h 查看命令）")
    else:
        print("输入序号选择；直接输入文字＝自由发言（/h 查看命令）")


def parse_player_input(
    line: str, ix: dict[str, Any]
) -> tuple[str, str | dict[str, Any]]:
    """把一行输入翻译成 (动作, 负载)。

    动作是命令 kind（choose_option/free_input/intervene/switch_scene），
    或控制动作 quit/help/menu/scenes/show。`show` 的负载是待打印的提示。
    """
    text = line.strip()
    if text in ("/q", "/quit", "quit", "exit"):
        return "quit", ""
    if text in ("/h", "/help", "?"):
        return "help", ""
    if text in ("", "/m", "/menu"):
        return "menu", ""
    if text.startswith("/s"):
        rest = text[2:].strip()
        scenes = _other_scenes(ix)
        if not rest:
            return "scenes", ""
        try:
            index = int(rest)
        except ValueError:
            return "show", "用法：/s 序号"
        if 1 <= index <= len(scenes):
            return "switch_scene", {"scene_key": scenes[index - 1]["scene_key"]}
        return "show", f"没有第 {index} 个可前往地点（共 {len(scenes)} 个）"
    if text.startswith("/i"):
        reason = text[2:].strip()
        if not reason:
            return "show", "用法：/i 你想要的干涉"
        return "intervene", {"text": reason}
    options = ix.get("options") or []
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(options):
            return "choose_option", {"option_id": options[index - 1]["option_id"]}
        return "show", f"没有第 {index} 个选项（共 {len(options)} 个）"
    if ix.get("mode") == "options" and options:
        return "show", "当前只能按序号选择"
    return "free_input", {"text": text}


def print_scenes(ix: dict[str, Any]) -> None:
    scenes = _other_scenes(ix)
    if not scenes:
        print("当前没有可前往的其他地点。")
        return
    print("\n==可前往的地点==")
    for index, scene in enumerate(scenes, 1):
        print(f'  {index}. {scene.get("title", "")}  [{scene.get("scene_key", "")}]')


async def read_player_input(prompt: str = "> ") -> str:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(None, input, prompt)
    except EOFError:
        return "/q"


class CommandError(RuntimeError):
    """服务端返回 error envelope。"""


class Recorder:
    """把一次试运行的所有材料写到 run 目录。"""

    def __init__(self, out: Path, *, base: str, script_id: int) -> None:
        self.out = out
        self.out.mkdir(parents=True, exist_ok=True)
        self.base = base
        self.script_id = script_id
        self.started = time.monotonic()
        self.messages = self._open("ws_messages.jsonl")
        self.transcript = self._open("transcript.md")
        self.session_id: str | None = None
        self.turns: list[dict[str, Any]] = []
        self.stage_events: list[dict[str, Any]] = []
        self.stream_deltas = 0
        self.audio_frames = 0
        self.errors: list[dict[str, Any]] = []

    def _open(self, name: str):
        f = (self.out / name).open("a", encoding="utf-8")
        if f.tell() == 0:
            if name.endswith(".md"):
                f.write("# Stage3 试运行进程记录\n\n")
        return f

    def write(self, line: str = "") -> None:
        self.transcript.write(line + "\n")
        self.transcript.flush()

    def heading(self, text: str) -> None:
        self.write(f"\n## {text}\n")
        print(f"\n=== {text} ===", flush=True)

    def ws(self, direction: str, msg: dict[str, Any]) -> None:
        self.messages.write(
            json.dumps({"ts": _now(), "dir": direction, "msg": msg}, ensure_ascii=False) + "\n"
        )
        self.messages.flush()

    def record_payload(self, direction: str, raw: Any) -> None:
        self.messages.write(
            json.dumps({"ts": _now(), "dir": direction, "raw": raw}, ensure_ascii=False) + "\n"
        )
        self.messages.flush()

    def close(self) -> None:
        self.messages.close()
        self.transcript.close()


async def login(http: httpx.AsyncClient, identifier: str, password: str) -> str:
    resp = await http.post(
        "/api/auth/login", json={"identifier": identifier, "password": password}
    )
    if resp.status_code != 200:
        raise SystemExit(f"登录失败 {resp.status_code}: {resp.text[:300]}")
    csrf = resp.json()["csrf_token"]
    http.headers["X-CSRF-Token"] = csrf
    return csrf


def _cookie_header(http: httpx.AsyncClient) -> str:
    return "; ".join(f"{c.name}={c.value}" for c in http.cookies.jar)


def _command(session_id: str, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "submit_command",
        "command": {
            "command_id": str(uuid.uuid4()),
            "session_id": session_id,
            "kind": kind,
            "payload": payload,
            "issued_at": _now(),
        },
    }


async def wait_for_interaction(
    ws: Any,
    rec: Recorder,
    *,
    timeout: float,
    stop_on_ended: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    """读到下一个交互点为止；返回 (消息批次, interaction, ended)。"""
    batch: list[dict[str, Any]] = []
    while True:
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=timeout)
        except TimeoutError as exc:
            raise TimeoutError(
                f"等待交互点超时（{timeout:.0f}s），最近消息：{_short(str(batch[-1:]), 300)}"
            ) from exc
        if isinstance(raw, bytes):
            rec.audio_frames += 1
            rec.record_payload("in", f"<binary {len(raw)} bytes>")
            continue
        msg = json.loads(raw)
        rec.ws("in", msg)
        t = msg.get("type", "")
        if t.startswith("stream_"):
            rec.stream_deltas += 1
            continue
        if t.startswith("audio_"):
            continue
        if t == "error":
            rec.errors.append(msg)
            p = msg.get("payload") or {}
            raise CommandError(f'{p.get("code")}: {p.get("message")}')
        if t == "asset_ready":
            continue
        batch.append(msg)
        text = _msg_text(msg)
        if text:
            rec.write(f"- `{t}` {_short(text, 300)}")
        if t == "interaction":
            return batch, msg.get("payload", {}).get("interaction"), False
        if t == "system":
            if "已结束" in text:
                return batch, None, True
            if stop_on_ended:
                return batch, None, True


async def send_and_drain(
    ws: Any,
    rec: Recorder,
    session_id: str,
    kind: str,
    payload: dict[str, Any],
    *,
    timeout: float,
    stop_on_ended: bool = False,
    echo: bool = True,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
    # command_id 在重试间保持不变：命令路径自带幂等闸，重发同一 id 是安全的。
    msg = _command(session_id, kind, payload)
    for attempt in range(1, 4):
        if attempt > 1:
            await asyncio.sleep(0.5 * attempt)
            rec.write(
                f"\n> ⚠ SESSION_CONFLICT（配图等命令外事件抢版本），"
                f"用同一 command_id 重试 {attempt}/3"
            )
            print(f"⚠ SESSION_CONFLICT，重试 {attempt}/3", flush=True)
        rec.ws("out", msg)
        rec.write(f"\n> 命令 `{kind}` {json.dumps(payload, ensure_ascii=False)}")
        if echo:
            print(f"→ {kind} {json.dumps(payload, ensure_ascii=False)[:120]}", flush=True)
        await ws.send(json.dumps(msg, ensure_ascii=False))
        try:
            return await wait_for_interaction(
                ws, rec, timeout=timeout, stop_on_ended=stop_on_ended
            )
        except CommandError as exc:
            # 只重试乐观锁冲突：此时事务未提交，重发不会双写；
            # 其他错误（含幂等命中后语义异常）重试可能卡在等不到交互点。
            if "SESSION_CONFLICT" not in str(exc) or attempt == 3:
                raise
    raise AssertionError("unreachable")


async def play_stage2(
    ws: Any, rec: Recorder, session_id: str, role: str, *, timeout: float
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """选角并自动推进 Stage2，直到进入 Stage3；返回 (首个交互点, 开场消息批次)。"""
    rec.heading("Stage2：选角并播放课文还原（自动）")
    _, ix, _ = await send_and_drain(
        ws, rec, session_id, "select_role", {"role_name": role}, timeout=timeout
    )
    if ix is None:
        raise SystemExit("选角后没有交互点")
    print(f"选角完成：{ix.get('mode')}", flush=True)

    for round_no in range(1, 61):
        mode = ix.get("mode")
        if mode != "options":
            break
        prompt = ix.get("prompt", "")
        if "结局" in prompt:
            rec.write(f"\n### 到达结局确认点（第 {round_no} 轮）")
            # 结局选择 + enter_stage3 连发：服务端串行处理，第二个命令会带出首个交互点。
            ending_option = (ix.get("options") or [{"option_id": "0"}])[0]["option_id"]
            for pending in (
                _command(session_id, "choose_option", {"option_id": ending_option}),
                _command(session_id, "enter_stage3", {}),
            ):
                rec.ws("out", pending)
                await ws.send(json.dumps(pending, ensure_ascii=False))
            batch, ix, _ = await wait_for_interaction(ws, rec, timeout=timeout)
            if ix is None:
                raise SystemExit("enter_stage3 后没有交互点")
            rec.stage_events.append(
                {"at": _now(), "stage": "stage3_extending", "mode": ix.get("mode")}
            )
            rec.write(f"\n### 进入 Stage3（mode={ix.get('mode')}）")
            return ix, batch

        options = ix.get("options") or []
        if not options:
            raise SystemExit(f"第 {round_no} 轮交互点没有选项：{_short(prompt)}")
        option_id = options[round_no % len(options)]["option_id"]
        _, ix, ended = await send_and_drain(
            ws,
            rec,
            session_id,
            "choose_option",
            {"option_id": option_id},
            timeout=timeout,
        )
        if ended or ix is None:
            raise SystemExit("Stage2 意外结束")
    raise SystemExit("Stage2 超过 60 轮仍未到达结局确认点")


def pick_command(
    ix: dict[str, Any],
    turn: int,
    rng: random.Random,
    *,
    intervene_every: int,
    switch_every: int,
) -> tuple[str, dict[str, Any]]:
    """模拟用户策略：优先用当前模式允许的输入，偶尔换景/干涉世界。"""
    mode = ix.get("mode")
    scene_options = [
        s for s in (ix.get("scene_options") or []) if not s.get("is_current")
    ]
    if scene_options and switch_every > 0 and turn % switch_every == 0:
        target = scene_options[(turn // switch_every) % len(scene_options)]
        return "switch_scene", {"scene_key": target["scene_key"]}
    if intervene_every > 0 and turn % intervene_every == 0:
        return "intervene", {"text": INTERVENTIONS[(turn // intervene_every) % len(INTERVENTIONS)]}

    options = ix.get("options") or []
    if mode in ("options", "options_with_fallback") and options:
        # 大部分时候选第一项（主线），偶尔随机，验证不同选项都能推进。
        option = options[0] if rng.random() < 0.75 else rng.choice(options)
        return "choose_option", {"option_id": option["option_id"]}
    text = FREE_INPUTS[turn % len(FREE_INPUTS)]
    return "free_input", {"text": text}


async def play_stage3(
    ws: Any,
    rec: Recorder,
    session_id: str,
    ix: dict[str, Any],
    *,
    turns: int,
    timeout: float,
    seed: int,
    intervene_every: int,
    switch_every: int,
) -> None:
    rec.heading(f"Stage3：自由探索 {turns} 个 turn")
    rng = random.Random(seed)
    for turn in range(1, turns + 1):
        if ix is None:
            raise SystemExit(f"第 {turn} 个 turn 开始前没有交互点")
        kind, payload = pick_command(
            ix,
            turn,
            rng,
            intervene_every=intervene_every,
            switch_every=switch_every,
        )
        rec.write(f"\n### Turn {turn}/{turns}")
        print(f"\n{TURN_MARK} Turn {turn}/{turns} [{ix.get('mode')}] {kind}", flush=True)
        started = time.monotonic()
        before_ix = ix.get("interaction_id")
        try:
            batch, ix, ended = await send_and_drain(
                ws, rec, session_id, kind, payload, timeout=timeout
            )
        except CommandError as exc:
            if kind not in ("intervene", "switch_scene"):
                raise
            # 可选动作（干涉/换景）可能被世界规则拒绝：记录后回落到常规输入，
            # 不把一次被拒的探索当成整场试运行失败。
            rec.write(f"\n> ⚠ 可选命令 `{kind}` 被拒绝，回落常规输入：{exc}")
            print(f"⚠ {kind} 被拒，回落常规输入", flush=True)
            fallback_kind, fallback_payload = pick_command(
                ix,
                turn,
                rng,
                intervene_every=0,
                switch_every=0,
            )
            batch, ix, ended = await send_and_drain(
                ws,
                rec,
                session_id,
                fallback_kind,
                fallback_payload,
                timeout=timeout,
            )
            kind, payload = fallback_kind, fallback_payload
        elapsed = time.monotonic() - started
        after_ix = (ix or {}).get("interaction_id")
        produced = [
            m.get("type")
            for m in batch
            if m.get("type") in ("narrative", "character_speech", "system")
        ]
        rec.turns.append(
            {
                "turn": turn,
                "command": {"kind": kind, "payload": payload},
                "elapsed_s": round(elapsed, 2),
                "messages": produced,
                "interaction_before": before_ix,
                "interaction_after": after_ix,
                "ended": ended,
                "mode_after": (ix or {}).get("mode"),
            }
        )
        print(
            f"← {len(batch)} 条消息 / {elapsed:.1f}s / "
            f"{'ended' if ended else f'next={after_ix}'}",
            flush=True,
        )
        if ended:
            rec.write("\n### 游戏已结束")
            return
        if ix is None:
            raise SystemExit(f"第 {turn} 个 turn 后没有交互点（stage 可能异常）")
        if after_ix == before_ix:
            rec.write("\n> ⚠ 交互点 ID 未变化，turn 可能没有真正推进")


async def play_interactive(
    ws: Any,
    rec: Recorder,
    session_id: str,
    ix: dict[str, Any],
    opening: list[dict[str, Any]],
    *,
    timeout: float,
    max_turns: int,
) -> None:
    """命令行交互循环：展示剧情 → 读玩家输入 → 推进一轮。"""
    rec.heading("Stage3：自由探索（命令行交互）")
    if opening:
        render_batch(opening)
    print("输入 /h 查看命令；直接输入文字即自由发言。", flush=True)
    turn = 0
    while True:
        if ix is None:
            raise SystemExit("没有交互点，无法继续")
        render_interaction(ix)
        line = await read_player_input("> ")
        kind, payload = parse_player_input(line, ix)
        if kind == "quit":
            rec.write(f"\n> 玩家退出：{line.strip()}")
            print("退出本局。", flush=True)
            return
        if kind == "help":
            print("\n" + HELP_TEXT, flush=True)
            continue
        if kind == "menu":
            continue
        if kind == "scenes":
            print_scenes(ix)
            continue
        if kind == "show":
            print(payload, flush=True)
            continue
        if max_turns and turn >= max_turns:
            rec.write(f"\n### 达到 --turns {max_turns}，停止推进")
            print(f"已达到 --turns {max_turns}，停止推进。", flush=True)
            return

        turn += 1
        rec.write(f"\n### Turn {turn}\n> 玩家：{line.strip()}")
        before_ix = ix.get("interaction_id")
        started = time.monotonic()
        try:
            batch, ix, ended = await send_and_drain(
                ws, rec, session_id, kind, payload, timeout=timeout, echo=False
            )
        except CommandError as exc:
            turn -= 1
            rec.write(f"\n> ⚠ 命令被拒绝：{exc}")
            print(f"\n⚠ 命令被拒绝：{exc}", flush=True)
            continue
        elapsed = time.monotonic() - started
        render_batch(batch)
        after_ix = (ix or {}).get("interaction_id")
        rec.turns.append(
            {
                "turn": turn,
                "command": {"kind": kind, "payload": payload},
                "elapsed_s": round(elapsed, 2),
                "messages": [
                    m.get("type")
                    for m in batch
                    if m.get("type") in ("narrative", "character_speech", "system")
                ],
                "interaction_before": before_ix,
                "interaction_after": after_ix,
                "ended": ended,
                "mode_after": (ix or {}).get("mode"),
            }
        )
        print(f"\n（第 {turn} 轮推进完成，{elapsed:.1f}s）", flush=True)
        if after_ix == before_ix and not ended:
            rec.write("\n> ⚠ 交互点 ID 未变化，turn 可能没有真正推进")
        if ended:
            rec.write("\n### 游戏已结束")
            return
        if ix is None:
            raise SystemExit(f"第 {turn} 个 turn 后没有交互点（stage 可能异常）")


async def dump_timeline(
    http: httpx.AsyncClient, rec: Recorder, session_id: str, out: Path
) -> None:
    resp = await http.get(f"/api/sessions/{session_id}/timeline")
    if resp.status_code != 200:
        rec.write(f"\n> timeline 拉取失败 {resp.status_code}: {resp.text[:200]}")
        return
    data = resp.json()
    (out / "timeline.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    entries = data.get("entries") or []
    rec.heading(f"时间线：{len(entries)} 条已发生事件")
    for entry in entries[-12:]:
        rec.write(
            f'- `{entry.get("sequence")}` {entry.get("kind")} '
            f'{_short(entry.get("speaker") or "", 12)} {_short(entry.get("text", ""), 120)}'
        )


def find_instance_dir(repo: Path, session_id: str) -> Path | None:
    for candidate in (
        repo / "backend" / "data" / "instances" / session_id,
        repo / "data" / "instances" / session_id,
    ):
        if candidate.is_dir():
            return candidate
    return None


def collect_instance(repo: Path, session_id: str, out: Path) -> tuple[str, int] | None:
    """把实例事件流复制进产物目录；返回 (目录, 行数)。"""
    instance_dir = find_instance_dir(repo, session_id)
    if instance_dir is None:
        return None
    events = instance_dir / "events.jsonl"
    if not events.exists():
        return str(instance_dir), 0
    payload = events.read_bytes()
    (out / "instance_events.jsonl").write_bytes(payload)
    return str(instance_dir), payload.count(b"\n")


async def main() -> int:
    parser = argparse.ArgumentParser(description="Stage3 自由探索试运行客户端")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--identifier", default=DEFAULT_IDENTIFIER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--script-id", type=int, default=DEFAULT_SCRIPT_ID)
    parser.add_argument(
        "--auto", action="store_true", help="脚本化自动推进（默认是命令行交互）"
    )
    parser.add_argument(
        "--turns",
        type=int,
        default=None,
        help="自动模式默认 8 轮；交互模式为推进上限，缺省不限",
    )
    parser.add_argument("--timeout", type=float, default=300.0, help="单条命令超时秒")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument(
        "--intervene-every", type=int, default=0, help="每 N 个 turn 干涉一次；0=关闭"
    )
    parser.add_argument(
        "--switch-every", type=int, default=0, help="每 N 个 turn 换景一次；0=关闭"
    )
    parser.add_argument("--keep-open", action="store_true", help="结束时不下 exit_game")
    parser.add_argument("--out", default=None, help="产物目录（默认 test/runs/<ts>）")
    args = parser.parse_args()

    # 输出重定向到文件时也保持逐行刷新，交互提示才能实时可见。
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(line_buffering=True)

    repo = Path(__file__).resolve().parents[1]
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else repo / "test" / "runs" / ts
    base = args.base.rstrip("/")
    rec = Recorder(out, base=base, script_id=args.script_id)
    summary: dict[str, Any] = {
        "started_at": _now(),
        "base": base,
        "script_id": args.script_id,
        "mode": "auto" if args.auto else "interactive",
        "turns_requested": args.turns,
        "seed": args.seed,
        "out": str(out),
        "ok": False,
    }
    print(f"产物目录：{out}", flush=True)

    http = httpx.AsyncClient(base_url=base, timeout=args.timeout)
    ws = None
    try:
        rec.heading("登录")
        await login(http, args.identifier, args.password)
        print(f"登录成功：{args.identifier}", flush=True)

        rec.heading("开局")
        resp = await http.post("/api/sessions", json={"script_id": args.script_id})
        if resp.status_code != 201:
            raise SystemExit(f"开局失败 {resp.status_code}: {resp.text[:400]}")
        status = resp.json()
        session_id = status["session_id"]
        rec.session_id = session_id
        summary.update(
            session_id=session_id,
            playable_roles=status.get("playable_roles"),
            stage_after_create=status.get("stage"),
        )
        rec.write(f"- session_id: `{session_id}`")
        rec.write(f"- 可扮演角色: {status.get('playable_roles')}")
        print(f"session_id = {session_id}", flush=True)
        print(f"playable_roles = {status.get('playable_roles')}", flush=True)

        ws_url = base.replace("http", "ws", 1) + f"/ws/{session_id}"
        rec.heading("连接 WS")
        async with websockets.connect(
            ws_url,
            additional_headers={"Cookie": _cookie_header(http)},
            ping_interval=None,
            max_size=16 * 1024 * 1024,
        ) as ws:
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            init = json.loads(raw)
            rec.ws("in", init)
            init_payload = init.get("payload") or {}
            summary.update(
                stage_after_init=init_payload.get("stage"),
                player_role_after_init=init_payload.get("player_role"),
                allowed_commands_after_init=init_payload.get("allowed_commands"),
            )
            rec.write(
                f"- session_init stage={init_payload.get('stage')} "
                f"allowed={init_payload.get('allowed_commands')}"
            )
            print(
                f"session_init stage={init_payload.get('stage')} "
                f"allowed={init_payload.get('allowed_commands')}",
                flush=True,
            )

            roles = status.get("playable_roles") or []
            if not roles:
                raise SystemExit("剧本没有可扮演角色")
            ix, opening = await play_stage2(
                ws, rec, session_id, roles[0], timeout=args.timeout
            )

            if args.auto:
                await play_stage3(
                    ws,
                    rec,
                    session_id,
                    ix,
                    turns=args.turns if args.turns is not None else 8,
                    timeout=args.timeout,
                    seed=args.seed,
                    intervene_every=args.intervene_every,
                    switch_every=args.switch_every,
                )
            else:
                print(
                    f"\n进入自由探索。当前场景：{init_payload.get('scene_title') or '未知'}",
                    flush=True,
                )
                await play_interactive(
                    ws,
                    rec,
                    session_id,
                    ix,
                    opening,
                    timeout=args.timeout,
                    max_turns=args.turns or 0,
                )
            summary["turns_completed"] = len(rec.turns)

            if not args.keep_open:
                rec.heading("退出游戏")
                batch, _, _ = await send_and_drain(
                    ws,
                    rec,
                    session_id,
                    "exit_game",
                    {},
                    timeout=args.timeout,
                    stop_on_ended=True,
                    echo=args.auto,
                )
                if not args.auto:
                    render_batch(batch)
            else:
                rec.write("\n### --keep-open：保留会话不退出")
                print("--keep-open：保留会话不退出", flush=True)

        rec.heading("时间线")
        await dump_timeline(http, rec, session_id, out)

        collected = collect_instance(repo, session_id, out)
        if collected is not None:
            summary["instance_dir"], summary["instance_events"] = collected
        summary["ok"] = True
        return 0
    except (CommandError, TimeoutError, SystemExit) as exc:
        summary["error"] = f"{type(exc).__name__}: {exc}"
        rec.write(f"\n### 失败：{summary['error']}")
        print(f"\n失败：{summary['error']}", file=sys.stderr, flush=True)
        if rec.session_id:
            try:
                await dump_timeline(http, rec, rec.session_id, out)
                collected = collect_instance(repo, rec.session_id, out)
                if collected is not None:
                    summary["instance_dir"], summary["instance_events"] = collected
            except Exception:  # noqa: BLE001 - 失败路径尽力记录
                pass
        return 1
    except Exception as exc:  # noqa: BLE001 - 连不上/协议异常也要留痕
        summary["error"] = f"{type(exc).__name__}: {exc}"
        rec.write(f"\n### 失败：{summary['error']}")
        print(f"\n失败：{summary['error']}", file=sys.stderr, flush=True)
        if rec.session_id:
            collected = collect_instance(repo, rec.session_id, out)
            if collected is not None:
                summary["instance_dir"], summary["instance_events"] = collected
        return 1
    finally:
        summary["finished_at"] = _now()
        summary["elapsed_s"] = round(time.monotonic() - rec.started, 1)
        summary["messages_total"] = sum(1 for _ in (out / "ws_messages.jsonl").open())
        summary["stream_deltas"] = rec.stream_deltas
        summary["audio_frames"] = rec.audio_frames
        summary["errors"] = rec.errors
        summary["turns"] = rec.turns
        summary["stage_events"] = rec.stage_events
        (out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        rec.close()
        await http.aclose()
        print(
            f"\n完成：ok={summary.get('ok')} turns={len(rec.turns)} "
            f"elapsed={summary.get('elapsed_s')}s → {out / 'summary.json'}",
            flush=True,
        )


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
