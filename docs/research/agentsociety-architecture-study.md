# AgentSociety 架构与「沙箱内多 Agent」维护机制调研

> 调研日期：2026-11-01
> 调研对象：<https://github.com/tsinghua-fib-lab/agentsociety> 浅克隆快照
> 快照：`3d359288d3c513f6c9f77afbaa9c16e205693f83`（2026-10-30），`agentsociety2` 版本 **2.9.3**
> 调研方式：只读源码，逐文件核对；未采信论文/博客的二手描述。下文 `AS2` =
> `packages/agentsociety2/agentsociety2/`，`v1` = `packages/agentsociety/agentsociety/`。
> **结论可能过期、非规格**：这是调研快照，不构成本项目的架构决策；若要采纳，先写 ADR。

## 结论（先看这段）

**不建议整体参考，更不建议把 WenJing 的运行期改成它的形态。** 它解决的是「开放世界、千级到百万级
人口、由 tick 驱动」的社科仿真；WenJing 是「有剧本、2–6 个角色、由玩家命令驱动」的封闭叙事游戏。
两者对「状态权威、时间推进、agent 生命周期」的假设相反。照搬会引入 Ray、每步重建、通用环境路由
等一整套 WenJing 不需要的复杂度。

**值得抄的只有三个工程细节**（按性价比排序）：

1. **prompt 前缀缓存纪律**：messages 一次构建、之后只 append，禁止每轮重建/截断
   （`AS2/agent/base/agent.py:1919-1936`）。WenJing 的角色 Agent 在构造时建一次
   `create_agent` executor，每轮 `ainvoke` 只传单条 `HumanMessage`
   （`backend/app/domain/agents/character.py:112-120,196`），system + tools 前缀天然稳定；
   值得加一条回归断言，防止未来改成分轮重建历史时悄悄丢掉缓存收益。
2. **用确定性 CLI 脚本承载「技能流程」**：`SKILL.md` 只做说明与选择，状态校验、序列化、
   时钟推导全在脚本里，返回 `{ok, ...}` 与可修复提示（`AS2/agent/skills/daily-guidance/SKILL.md`
   + `scripts/daily_guidance.py`）。这个思路可借鉴到 WenJing 的教师侧操作/生成期工具，
   但**不要**把 prompt 从 DB 搬到文件，那会破坏 `prompts` 表单源。
3. **token 用量里单独记 `cached_input` 与缓存命中率**（`AS2/society/society.py:246-254,600-640`；
   `AS2/config/llm_dispatcher.py:365-446`）。WenJing 的 `llm_usage` 目前只有
   prompt/completion/total（`backend/app/infrastructure/usage/recorder.py:73-96`），
   加上 cached 分量才能验证「分层 prompt 到底省没省钱」。

**以下明确不要抄**：

- **Ray + record-based 每 tick 重建**：WenJing 单 worker、单命令串行，`_RState` +
  `export_state/restore` 已经是同构的「显式状态」方案（`backend/app/domain/game/game_runtime.py:1-20,54-86`），
  且角色只有个位数，磁盘重建是纯开销。
- **CodeGenRouter「LLM 写 Python 调环境」**：与 ADR-0004 已选定的 LangChain tool calling 冲突；
  其所谓 sandbox 只是进程内 restricted `exec`，不是安全边界（见 §4）。
- **AgentBase 式 3000 行基类**：`AS2/agent/base/agent.py` 3155 行、73 个方法，是明确的反面教材。
- **v1 的 Block + Memory 全套认知架构**：v2 自己已经删掉了（见 §5），这是最强的「不要建」信号。

**关于「沙箱」需要先澄清**：这个仓库**没有** OS/容器级 agent 沙箱。它有三层容易混淆的「隔离」：
① 每个 agent 一个 workspace 目录；② 环境代码生成的 restricted `exec`；③ skill 脚本的进程内执行。
三者都不是多租户安全边界（§4）。WenJing 若将来要让教师/学生提交可执行内容，不能照这个做。

---

## 1. 仓库快照与规模

| 项 | 值 |
|---|---|
| 主包 | `packages/agentsociety2`（v2，推荐）；`packages/agentsociety`（v1，legacy） |
| 版本 | 2.9.3（`packages/agentsociety2/pyproject.toml:7`） |
| 快照 commit | `3d3592`，2026-10-30 |
| Python 文件 | 641（全仓）/ 217（`AS2`） |
| 核心代码量 | agent/env/society/storage/config 约 26k 行 |
| 测试 | 203 个 `test_*` 函数 |
| 质量闸门 | ruff + ruff-format + pre-commit；CI 跑 ruff、pytest、CodeQL（`.github/workflows/ci.yml`） |
| **类型检查** | **仅 `mypy tests/ --follow-imports=skip`，源码不被 mypy 约束**（`ci.yml:59-61`；`pyproject.toml:223` 只有 `python_version`） |

仓库自述的定位见 `CLAUDE.md`「Architecture」与 `README.md:38-125`：v2 是「LLM-native agent
simulation platform」，v1 是「gRPC-based city simulation」。v2 明确把 `extension/`（VSCode
AI Social Scientist）与 `frontend/` 纳入活跃范围，legacy 包只做参考（`AGENTS.md`）。

## 2. 架构总览（v2）

```
CLI / FastAPI(:8001) / React / VSCode extension
                    │
             AgentSociety（编排器，只持 specs + ids）
        ┌───────────┼──────────────────────┐
   step_agent_batch  env_router(actor)   ReplayWriter(JSONL)
   (Ray Task, 每批 N)   (CodeGen/ReAct/Plan)   (sharded, DuckDB 读)
        │                                   │
   agent workspace                     trace (JSONL spans)
   agent_<id>/AGENT.json
```

关键分层（`AS2`）：

- **society**：`AgentSociety` 只持 `agent_specs`、`agent_ids` 与句柄，**不持 agent 对象**
  （`society/society.py:1-20,104-134,166-220`）。`step()` 的顺序是：
  推时钟 → 切批提交 `step_agent_batch` Ray Task → 等全部完成 → `env.step` → 时钟前进 →
  落盘（`society/society.py:772-843`）。
- **agent**：`AgentBase` 拥有 workspace 绑定、skill runtime、ReAct 循环、LLM、TODO、trace、
  `AGENT.json` 持久化（`agent/base/agent.py`）。`PersonAgent` 只覆盖
  `build_react_messages` / `dispatch_react_tool`（`agent/person.py:269-369`）。
- **env**：`EnvBase` + `@tool` 装饰器把方法注册成工具，`RouterBase` 的多个实现
  （CodeGen 默认、ReAct、PlanExecute、TwoTier、SearchTool）负责把 agent 的 `ask` 翻译成
  环境调用（`env/base.py:1-30,368-460`；`CLAUDE.md`「Environment Router」）。
  生产路径把 router 放进独立 Ray actor（`env/env_router_actor.py:1-18`，
  `env/env_router_proxy.py:1-13`）。
- **storage**：回放从「中心 SQLite actor」改为「每进程 append-only、按 CRC32 分 256 片的
  JSONL + `_schema.json` 目录」，读侧用 DuckDB（`storage/replay_sink.py:1-21,100-140`；
  `storage/replay_reader.py:1-60`）。
- **config**：每个 event loop 自建 litellm Router + AIMD 信号量，**没有模块级全局缓存**
  （`config/llm_dispatcher.py:1-17,148-260`），解决了 Ray `asyncio.run` 每任务一个 loop
  导致的「bound to a different event loop」。

## 3. 「沙箱内多 Agent」到底怎么维护

### 3.1 时间推进：先 agent，后 env，所有人看同一份 step 前状态

`society.step()` 先把 `current_time` 推给 env（`society/society.py:791-793`），再 fan-out
所有 agent；agent 的工具调用可以改 env，但 env 的 `step()` 在**所有 agent 完成之后**才推进
（`society/society.py:838-843`）。这是典型的「同时行动 + 统一结算」：
同一 step 内没有先后因果，只有结算时刻的全局状态变化。

WenJing 是反过来的：玩家命令是唯一输入，`GameRuntime.submit` 从当前稳定交互点推进到下一个
稳定交互点（`game_runtime.py:1-9`）。**不要**把 WenJing 改成 tick 制——叙事节拍不是均匀时间。

### 3.2 Agent 不是常驻对象，而是「每步从磁盘重建的 record」

driver 只持 `agent_ids`；每个 Ray Task 对批内每个 id 执行
`from_workspace → step → to_workspace`，只回传轻量 dict（`agent/runner.py:122-156,289-333`）。
批内 `asyncio.gather` 并发，全局 LLM 并发由 dispatcher 的 `AdaptiveSemaphore` 控制；
单个 agent 抛错只记录 `{"ok": False, "error": ...}`，不拖垮同批（`agent/runner.py:133-147`）。
driver 汇总后若有失败，仍然整 tick 抛 `RuntimeError`（`society/society.py:828-836`）——
即「批内隔离、tick 级失败」。

WenJing 已经有等价物且更便宜：`CharacterAgentManager` 按命令从快照恢复 memory
（`backend/app/domain/agents/character.py:286-330`），`GameRuntime` 用显式 `_RState`
+ `export_state/restore` 重建（`game_runtime.py:54-86`）。多角色提议也是
`asyncio.gather(..., return_exceptions=True)`，单角色失败只记 `propose_failed`
（`backend/app/domain/game/game_runtime.py:587-600`）。**这一项是「互相验证」，不是「需要迁移」。**

### 3.3 状态落盘与恢复

- 每个 agent 一个目录：`<workspace_root>/agent_<id:04d>/`，`config.json` 只写一次，
  `AGENT.json` 每步重写，另有 `state/`、`memory/`（`agent/runner.py:111-117`；
  `agent/person.py:188-205`）。
- 原子写：`tmp` + `os.replace`，崩溃不会留截断文件（`storage/workspace_state.py:1-30`）。
- society 级 checkpoint 拆成两份：不可变全量 `SOCIETY.json` 只在 init 写一次；
  每步只写标量 `SOCIETY_STEP.json`，避免每步重序列化大列表
  （`society/society.py:67-73,547-598`）。
- resume 用 `steps.yaml` 的 SHA-256 做漂移检测，防止编辑 steps 后位置型游标错位
  （`society/cli.py:377-413`）。

这套「不可变 + 每步增量」的分层 checkpoint 是合理的；但 WenJing 的 `SessionStore.commit`
已经是 DB 单事务 + CAS（ADR-0006），不需要文件 checkpoint。

### 3.4 并发控制

- agent 批：批内并发，批间由 driver 提交多个 Ray Task（`agent/runner.py:149-156`）。
- env：默认单 actor 串行；只有**所有**挂载模块都声明 `is_concurrency_safe()` 才把
  `max_concurrency` 开大（`CLAUDE.md`「Environment Router」；
  `env/env_router_actor.py:20-38`）。
- LLM：`AdaptiveSemaphore` 用 AIMD（延迟/429 反馈调容量），每个 loop 独立
  （`config/llm_dispatcher.py:148-260`）。

WenJing 是固定 `asyncio.Semaphore(5)`（`backend/app/infrastructure/llm/chat.py:62-75`）。
角色数只有个位数，固定值够用；除非生成期 fan-out 经常撞 429，否则不值得引入 AIMD。

### 3.5 环境路由：三套抽象叠在一起

1. `EnvBase` 的 `@tool(readonly=..., kind="observe"|"statistics")`：元类收集工具，
   装饰器包装调用历史（`env/base.py:88-320,343-460`）。`observe` 每步自动调用，
   `statistics` 无参、只读。
2. `RouterBase` 把工具信息格式化成类似 `.pyi` 的文本喂给 LLM，支持
   `_format_tools_pyi` / trimmed / ratio / raw_code 多种长度策略
   （`env/router_base.py:989-1386`）。这是「用 Python 类型签名当工具 schema」的做法，
   比 JSON schema 更省 token，但实现很重。
3. `CodeGenRouter`（默认）让 LLM 生成 Python 代码调用工具，再 AST 检查 + `exec`
   （`env/router_codegen.py:1-11,1273-1412`）。另有 ReAct / PlanExecute / TwoTier /
   SearchTool 四种路由（`env/router_*.py`）。

对 WenJing：`WorldView` 的只读工具已经够用（ADR-0004，`backend/app/domain/agents/tools.py`），
**不要**为了「通用环境模块」再引入一层 Router。

### 3.6 记忆：文件即数据库，v2 不做向量检索

- `MEMORY.md` = 压缩后的长期记忆；`memory/episodes.jsonl` = append-only 权威事件；
  `memory/state.json` = 游标/计数（`agent/memory.py:17-20`）。
- 检索只有 `recent()`、子串 `search()`、`range()`、`read_ids()`，**没有 embedding**
  （`agent/memory.py:515-613`）。
- 记忆生成内联在 step 模式的 `finish(memories=...)` 工具里，省掉一次抽取 LLM 调用
  （`agent/person_tools.py:110-153`；`agent/memory_runtime.py:314-320`）。
- `after_step` 校验 → 追加 episode → 按条数/间隔/重要度触发整篇 `MEMORY.md` 重写
  （`agent/memory_runtime.py:306-382,459-567`；阈值 `agent/memory.py:647-696`）。

WenJing 的 `CharacterMemory` 更轻（工作记忆 + 私有日志 + 剧情上下文 + 被驳回提议），
已经经过「机制层知识边界」裁剪（`character.py:44-69,88-108`）。AgentSociety 的
「episode 权威 + MEMORY.md 摘要」可以用在**长局 Stage3 续写**的角色记忆压缩上，
但当前 MVP 不需要。

### 3.7 技能：SKILL.md + 确定性脚本 + 生命周期钩子

- 技能是自包含目录：`SKILL.md`（YAML frontmatter：`name`/`description`/可选
  `script`/`hooks`）+ 可选 `scripts/<name>.py` + `references/`。
- 选择分两段：LLM 只先看 name/description 的目录（`skill_catalog()`），
  选中后才加载正文（`activated_skill_content_xml()`）
  （`agent/base/skill_runtime.py:341-357,540-575`；发现与扫描见
  `agent/base/skill_registry.py:101-160`）。
- 执行优先级：进程内 `entrypoint(argv, ctx)` → 无 entrypoint 时动态 `exec` 源码 →
  子进程兜底（`agent/base/skill_runtime.py:992-1020,1050-1219`）。
- `pre_step`/`post_step` 钩子渲染进专用 `<skill_hooks>` 块；钩子支持 contextvar 注入
  （`agent/base/skill_hook_context.py:20-84`）。
- 唯一内置技能 `daily-guidance`：LLM 提交一天的 JSON story，脚本负责校验、写 YAML、
  从仿真时钟推导 `completed_segments`，`pre_step` 每步注入当前 segment
  （`AS2/agent/skills/daily-guidance/SKILL.md:1-70`）。

**这是全仓库对 WenJing 最有借鉴价值的设计**：把「流程状态」放进确定性脚本，LLM 只负责
提交结构化意图；脚本返回 `{ok, next, repair hints}`，而不是让 LLM 自己维护状态机。
它和 WenJing「契约单源 + Pydantic 校验 + 事件溯源」是同一哲学，只是把「校验/推导」搬到了
技能脚本里。若要借鉴，建议落在**教师侧操作**（重新生成/检索替换/上传/删除）或
**生成期闸门编辑**（ADR-0003 的 `GateEdits.asset_ops`），而不是运行期角色。

## 4. 「沙箱」的真相：三层隔离，没有一层是安全边界

| 层 | 实现 | 能防什么 | 防不了什么 |
|---|---|---|---|
| workspace 目录 | `WorkspaceFS.resolve()` 用 `resolve+parents` 阻断路径逃逸（`agent/base/workspace_fs.py:106-118`）；`run_command` 只放行 `python`（`:299-322`） | 手滑写错路径、跑非 python 命令 | 同进程内其他代码、恶意 python 脚本 |
| 环境代码生成 | 白名单 builtins/modules + AST 黑名单 + 10s 超时 + 进程内 `exec`（`env/router_codegen.py:1273-1412,1582-1641`） | 模型生成的明显危险代码（`os`/`subprocess`/`eval`/`while True`） | 刻意逃逸：`getattr` 在白名单里，dunder 属性可达；`exec` 与 agent 同进程、同权限 |
| skill 脚本 | 默认进程内 `entrypoint` 或动态 `exec`；子进程只是兜底（`agent/base/skill_runtime.py:992-1020,1115+`） | 无 | 任意代码执行、读环境变量、访问宿主文件系统 |

作者自己在 `router_codegen.py:1316-1320` 写了注释：`print` 不能走全局 `sys.stdout`，
因为 64 并发下会串台——这恰好说明执行环境是**共享进程**，不是隔离沙箱。
`CodeGenRouter` 的 AST 检查可被 `().__class__.__mro__` 一类写法绕过；它适合
「信任生成器、只防模型犯蠢」的科研场景，**不适合**「教师/学生可提交内容」的多租户场景。
WenJing 若要做可执行技能，必须用子进程/容器 + 最小权限 + 资源限额，不能用 restricted `exec`。

## 5. v1 → v2 的演进：一份反面教材

v1 是经典的「生成式 agent」认知架构：

- `Agent` 持 blocks，`run()` 依次 `before_forward → before_blocks → forward →
  after_blocks → after_forward → status_summary`（`v1/agent/agent_base.py:391-456`）。
- `BlockDispatcher` 用一次 LLM 函数调用在 cognition/plan/mobility/needs/economy/social
  block 之间选一个（`v1/agent/dispatcher.py:75-135`）。
- `Memory` = `KVMemory`（带向量检索的字段）+ `StreamMemory`（时间序事件 + 相关性检索）
  + 向量库（`v1/memory/memory.py:22-120,283-530`）。
- 多 agent 协调靠 `SimulationEngine.gather()/filter()` 跨 agent 读状态
  （`v1/simulation/simulationengine.py:1044-1143`）。

v2 把这些**基本删光**：不再有 block 调度、不再有内置 memory 技能、不再有向量检索；
取而代之的是「一个 AgentBase + ReAct + skill 目录 + env tools + 文件记忆」。
`CLAUDE.md` 明确写「the old observation/cognition/plan/memory skills were removed」。
**这是最重要的信号**：连他们自己都认为那套认知架构的维护成本高于收益。WenJing 的
`CharacterMemory` + `STAGE_DIRECTIVES` + 工具查询（ADR-0004）已经落在 v2 的方向上，
不要回头去建 block/memory 框架。

## 6. 编码质量：工程化亮点与明显债

**亮点（可学）**

- 端口用 `Protocol` 而不是继承具体类：`EnvLike`/`LLMClientLike`/`TraceLike`/`ReplayLike`
  （`agent/service_proxy.py:20-90`），Ray 边界只传可序列化句柄。
- 不可变值对象：`ReactToolResult` 等 frozen dataclass（`agent/base/react.py:25-83`）。
- 路径安全、原子写、per-agent 失败隔离、Ray 缺失时优雅降级
  （`agent/runner.py:53-58`）、AIMD 并发、prompt 缓存纪律、`_schema.json` 自描述回放目录。
- 文档密度高：模块 docstring 讲清「为什么」，且大量注释记录实测数字（如缓存命中率
  52%→82%，`agent/base/agent.py:1921-1927`）。
- 测试 203 个，`asyncio_mode = "auto"`，网络测试用 marker 排除
  （`pyproject.toml` 的 pytest 配置）。

**债（不要学）**

- **god class**：`AgentBase` 3155 行 / 73 个方法；`CodeGenRouter` 2135 行 / 63 个方法；
  `RouterBase` 1510 行。虽然有组合缓解，但改一个生命周期钩子要在一屏外的代码里找。
- **异常吞噬**：`AS2` 内 290 处 `except Exception`；ruff 显式忽略 `BLE001`/`S110`/`S112`
  （`pyproject.toml:172-190`）。很多地方 `logger.debug` 后继续，失败现场会丢。
- **源码无类型闸门**：CI 只 mypy `tests/`，源码大量 `Any`；`py.typed` 宣称 typed，
  但类型正确性没有保证。
- **解析层正则汤**：文本工具调用解析 235 行（`agent/base/agent.py:2625-2858`）。
- **死代码/兼容别名**：`memory_consolidation_tool_schema()` 已无调用方
  （`agent/person_tools.py:156-183`）；`resolve_skill_id_by_name`/`activate_skill_by_name`
  等 deprecated alias（`agent/base/skill_runtime.py:475-538`）。
- **反向依赖**：`agent/base/agent.py:45-53` import `agent/person_prompt.py`，基类依赖子类层。

一句话：**研究型框架，迭代快，工程化「够用但不严」；可以借模式，不能当 coding standard 模板。**

## 7. 与 WenJing 的逐项对照

| 维度 | AgentSociety v2 | WenJing | 结论 |
|---|---|---|---|
| 场景 | 开放世界、tick 驱动、N 可到百万 | 封闭剧本、玩家命令驱动、2–6 角色 | 根本不同 |
| 状态权威 | workspace 文件 + `AGENT.json` | 事件流 + 快照（`EventStore`） | WenJing 更强 |
| agent 生命周期 | 每步 `from_workspace→step→to_workspace` | 每命令从快照重建 memory | 同构，已验证 |
| 时间推进 | 先 agent 后 env，统一结算 | 命令推进到下一个交互点 | 不要改 |
| 协调 | env router + 共享世界状态 | 剧本节拍 + 事件日志 + 知识边界 | WenJing 更适合叙事 |
| 记忆 | 文件 episode + MEMORY.md 摘要 | `CharacterMemory` 分层 + 工具查询 | WenJing 更轻 |
| 工具 | 5 种 Router，默认 LLM 写代码 | LangChain tool calling（ADR-0004） | 保持现状 |
| 持久化 | 分片 JSONL + DuckDB | PG 事件流 + 事务 CAS | WenJing 更强 |
| 并发 | Ray + AIMD + 单 env actor | 单 worker + 固定 semaphore | 不需要 |
| 隔离 | workspace 目录 + restricted exec | org/session 鉴权（无代码执行） | WenJing 更安全 |
| prompt | 单次构建 + append，前缀缓存 | 分层 system prompt + 工具查询 | 可加缓存指标 |

## 8. 建议（按优先级）

**P1（低成本、可验证，建议做）**

1. **prompt 前缀缓存回归测试**：给 `CharacterAgent._run` / `ScreenwriterAgent` 加一个
   用 scripted LLM 的测试，断言同一角色连续两次调用的 `system + tools` 前缀字节一致，
   且没有从头部截断历史。参考 `AS2/agent/base/agent.py:1919-1936` 的注释与实测数字。
2. **`llm_usage` 增加 `cached_input` 分量**：provider 回报的
   `prompt_tokens_details.cached_tokens` 落到新列，运营后台聚合缓存命中率
   （对照 `AS2/society/society.py:600-640` 的口径：`input` 是否含 cache read 要保留原值）。
   这会动契约四处（`contracts`/fixtures/jsonschema/types.ts），成本主要在流程，不在代码。

**P2（有明确场景再做）**

3. **教师侧「技能脚本」模式**：把 `GateEdits.asset_ops` 一类操作做成确定性 CLI/工具，
   返回 `{ok, next, repair}`，而不是让 LLM 自由生成 JSON。可借鉴
   `daily-guidance` 的「状态由脚本推导、LLM 只提交意图」。
4. **长局记忆压缩**：若 Stage3 续写出现 `working_memory` 膨胀，再参考
   episode 权威 + `MEMORY.md` 摘要 + 条数/重要度触发的做法（`agent/memory.py:647-696`），
   不要现在就建通用记忆框架。

**不做**

- Ray / record-based 每 tick 重建 / 通用 EnvBase + 5 种 Router / CodeGenRouter /
  v1 Block+Memory / 3000 行基类 / 文件式 society checkpoint。
- 任何「让 LLM 生成代码并 `exec`」的运行时扩展；若确需代码执行，用子进程 + 容器 + 限额。

## 9. 来源

- 仓库快照：`tsinghua-fib-lab/agentsociety` @ `3d3592`（2026-10-30），`agentsociety2` 2.9.3。
- 架构自述：`CLAUDE.md`、`AGENTS.md`、`README.md:38-125`、
  `packages/agentsociety2/pyproject.toml`。
- 编排：`AS2/society/society.py`、`AS2/society/cli.py`、`AS2/society/models.py`。
- agent：`AS2/agent/base/agent.py`、`AS2/agent/person.py`、`AS2/agent/runner.py`、
  `AS2/agent/service_proxy.py`、`AS2/agent/memory.py`、`AS2/agent/memory_runtime.py`、
  `AS2/agent/base/workspace_fs.py`、`AS2/agent/base/skill_runtime.py`。
- env：`AS2/env/base.py`、`AS2/env/router_base.py`、`AS2/env/router_codegen.py`、
  `AS2/env/env_router_actor.py`、`AS2/env/env_router_proxy.py`。
- storage/config：`AS2/storage/replay_sink.py`、`AS2/storage/replay_reader.py`、
  `AS2/storage/workspace_state.py`、`AS2/config/llm_dispatcher.py`。
- v1 对照：`v1/agent/agent_base.py`、`v1/agent/dispatcher.py`、`v1/memory/memory.py`、
  `v1/simulation/simulationengine.py`。
- 质量：`.github/workflows/ci.yml`、`.pre-commit-config.yaml`、`tests/`。
- 本项目对照：`docs/adr/0004-langchain-runtime-agents-and-tools.md`、
  `docs/adr/0006-composition-root-and-session-store.md`、`CONTEXT.md`、
  `backend/app/domain/game/game_runtime.py`、`backend/app/domain/agents/character.py`、
  `backend/app/infrastructure/usage/recorder.py`。
