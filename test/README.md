# Stage3 试运行客户端

黑盒客户端：对运行中的后端走真实协议（登录 → 开局 → WS 选角 → Stage2 播放 →
`enter_stage3`），默认进入**命令行交互**，每轮先展示剧情，再接受玩家输入；
`--auto` 退回脚本化自动推进。每一步的 WS 消息、命令、交互点、阶段变化都落盘，
用来回答「自由探索的 turn 能否顺利推进」。

不 import `app.*`，只依赖 `httpx` / `websockets`，所以它验证的是协议而不是内部实现。

## 前置

```bash
make db-up && make migrate && make seed
# 已发布剧本（默认背影 script_id=1）：见 backend/scripts/persist_recipe.py
cd backend && uv run uvicorn app.main:app --port 8000 --no-access-log
```

账号默认 `student / 123456`（`make seed` 创建）。

想要秒级、可重复的推进（CI/回归用）：用确定性 Agent LLM 起后端，
`cd backend && WENJING_LLM_API_KEY= uv run uvicorn app.main:app --port 8000 --no-access-log`，
同样能跑完整 Stage2→Stage3 链路（台词与选项走确定性兜底）。

## 用法

```bash
cd backend
uv run python ../test/stage3_playthrough.py                   # 交互式玩
uv run python ../test/stage3_playthrough.py --auto            # 自动 8 轮
uv run python ../test/stage3_playthrough.py --auto --turns 12 # 自动 12 轮
uv run python ../test/stage3_playthrough.py --turns 3         # 交互式，最多 3 轮
uv run python ../test/stage3_playthrough.py --keep-open       # 退出时不 exit_game
uv run python ../test/stage3_playthrough.py --script-id 1 --base http://localhost:8000
```

### 交互界面

每轮输出三段：

```
==角色发言和行为==
父亲：进去吧，里边没人。

==场景/故事更新==
【进入新场景：「车厢内外：我的自以为是」（在场：我、父亲）】
父亲 提议：（把黑布小帽正了正，转身蹒跚着走过铁道）

==请选择你的行为==
  1. 探头往车门口张望父亲的去向
  2. 摸出衣袋里的半封信就着光展平
可前往：/s 1=徐州奔丧与父亲的劝慰；/s 2=南京停留
输入序号选择；直接输入文字＝自由发言（/h 查看命令）
>
```

输入约定：

| 输入 | 行为 |
|------|------|
| `1` / `2` … | 选择对应序号的选项 |
| 任意文字 | `free_input` 自由发言（Stage3；Stage2 只接受序号） |
| `/s`、`/s N` | 列出 / 前往第 N 个地点（`switch_scene`） |
| `/i 文字` | 干涉世界（`intervene`，由 WorldBuilderAgent 解析） |
| `/m` | 重新显示当前交互点 |
| `/h` | 帮助 |
| `/q` | 退出本局（随后发 `exit_game`） |

Stage2 是课文还原，默认自动播放到结局，不打断交互；交互从 Stage3 开始。

常用参数：

| 参数 | 含义 |
|------|------|
| `--auto` | 脚本化自动推进（原试运行模式） |
| `--turns` | 自动模式默认 8 轮；交互模式为推进上限，缺省不限 |
| `--timeout` | 单条命令等待交互点的超时秒（真实 LLM 建议 ≥300） |
| `--seed` | 自动模式的选项随机种子，保证可复现 |
| `--intervene-every` | 自动模式每 N 轮发一次 `intervene`；0 关闭 |
| `--switch-every` | 自动模式每 N 轮发一次 `switch_scene`；0 关闭 |
| `--keep-open` | 结束时不发 `exit_game` |
| `--out` | 自定义产物目录 |

自动模式下，`intervene` / `switch_scene` 被世界规则拒绝时会回落成常规输入，
并在 transcript 里记一条 ⚠，不会让整场试运行失败；交互模式则把错误打出来，
让玩家重新输入。

## 产物

每次运行写 `test/runs/<时间戳>/`（已 gitignore）：

- `ws_messages.jsonl`：双向 WS 消息，含 `stream_*` / `audio_*` 瞬态消息；
- `transcript.md`：人读的剧情进程（命令、叙事、台词、交互点、换景列表）；
- `timeline.json`：`GET /api/sessions/{id}/timeline` 的活动分支事件；
- `instance_events.jsonl`：fs 记忆后端的实例事件镜像（含 `world_chronicle`）；
- `summary.json`：会话 ID、turn 统计（每 turn 的耗时/消息数/交互点 ID 变化）、
  阶段、错误、实例记忆目录与 `events.jsonl` 行数。

判断「turn 顺利推进」看三处：

1. `summary.json.turns` 里每个 turn 的 `interaction_after` 与下一个 turn 的
   `interaction_before` 不同，且 `messages` 里至少有叙事/台词之一；
2. `transcript.md` 里的 timeline 条数持续增长；
3. `instance_events.jsonl` 里有与 turn 数相当的 `world_chronicle` 事件。

## 已知噪声

- `stream_start/delta/end` 是逐字字幕，只计数不打印；权威文本是 `character_speech`。
- 无 TTS provider 时没有 `audio_*`，不是故障。
- `select_role` 在真实 LLM 下要跑角色提议 + 验证，可能分钟级，属于正常。
- 会话结束时服务端会回一条「已结束」的 `system` 消息；客户端的 `exit_game`
  等的是它。
- **`SESSION_CONFLICT` 是预期内的良性冲突**：命令在「恢复运行时 → 跑 LLM →
  提交」之间可能被命令外事件（运行期配图 `asset_ready`）抢走版本号。命令自带
  幂等闸，客户端会用**同一 `command_id`** 自动重试（最多 3 次）并在 transcript
  里记一条 ⚠；真实前端目前不自动重试，会直接提示「操作冲突，请刷新后重试」，
  这是服务端命令路径可以改进的点。
