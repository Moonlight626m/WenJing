# Wenjing — Agent Instructions

语文课文情景演绎 multi-agent 平台（FastAPI + Next.js）。**规格优先级**：GitHub Issue/spec > 代码与 `CONTEXT.md`（术语）。文档地图见 `docs/README.md`，术语以 `CONTEXT.md` 为准。历史上的架构决策（多用户化、LangGraph 生成 workflow、运行期 Agent 工具化、媒体/流式、组合根）已落地为代码，细节可查 git 历史（曾存于 `docs/adr/`，2026-11 删除）。

## 实现工作流

- 完成新功能/修复后，**用 `feat-review` 审查改动**（双轴：仓库 Standards + 原始 issue/ADR 合规），修复发现的问题再向用户汇报。审查结论要逐条复核再动手——两个方向都会误报，也会指出你自己新代码里的真 bug。
- `code-review`（内置，正确性 bug 猎手）与 `feat-review` 互补并存，**不是重名冲突**；需要纯正确性扇出排查时用前者。
- commit 用 Conventional Commits 前缀（`feat`/`fix`/`docs`…）；描述、注释、文档用中文。

## 命令

验证顺序：`make lint` → `make lint-arch` → `cd frontend && npm run typecheck` → `make test`。

- 单个测试：`cd backend && uv run pytest tests/test_x.py::test_y -q`
- 真实 LLM 全链路冒烟：`cd backend && uv run python -m scripts.smoke_workflow`（需 key）。
- 前端类型检查必须用 `npm run typecheck`（先 `next typegen` 再 `tsc --noEmit`）；直接 `tsc` 会因缺全局生成类型报 `TS2304`。Next.js 16 的 API/约定与训练数据不同，细节以 `frontend/AGENTS.md` 为准。
- 包管理器：后端 **uv**（`backend/uv.lock`），前端 **npm**（`frontend/package-lock.json`）。

## 架构

### 分层与依赖方向（`make lint-arch` 守卫，契约在 `backend/.importlinter`）

`backend/app/` 的六条 import-linter 契约合起来规定的可 import 范围（除此之外的横向引用不拦）：

| 层 | 可 import |
|----|----------|
| `controllers/`、`main.py` | 任意（含 `composition`） |
| `services/` | `services/`、`domain/`、`infrastructure/`、`contracts/` |
| `domain/` | `domain/`、`contracts/`，外加唯一白名单 `infrastructure.errx` |
| `infrastructure/` | `infrastructure/`、`domain/`、`contracts/` |
| `contracts/` | 仅 `contracts/`（契约名叫「零 `app.*` 依赖」，但拦截清单里漏了 `main`） |
| `composition.py` | `services/`、`domain/`、`infrastructure/`、`contracts/` |

两条最容易记反的：

- **`infrastructure/` 可以 import `domain/`**，反向不行。适配器实现 domain 端口、返回 domain 类型是允许方向（如 `ImageProcessor.process` 返回 `domain.game.media.Rendition`）。
- **`domain/` 对 `infrastructure/` 只有一个白名单 `errx`**，故 domain 内日志用标准库 `logging`，不要碰基础设施门面。

**`composition` 是唯一组合根**（`Container` + `get_container()`），除 `controllers/`、`main.py` 外**谁都不准 import 它**：lifespan 调 `container.open()`，controller 经它取单例服务；新增接缝/适配器加在这里，**不要**在 controller 里建模块级单例。

**`services/session_store.py` 是会话持久化的深模块**（`restore`/`commit`/`load_package`/`has_command`/`discard`）：命令路径与命令外事件路径共用同一套 CAS 事务拼写，改持久化语义只改这一处。

**`SessionApplication._lock_for` 是进程内会话写锁**：命令的「恢复 → LLM → 提交」与命令外事件（配图就绪、离线 tick、系统事件）共用同一把锁。版本 CAS 只作跨进程兜底——进程内不加锁时，配图事件会在命令跑完 LLM 后抢走版本号，命令直接失败；玩家（或客户端）重试就要重付一次 LLM。新增任何会推进 `session.version` 的写入路径时，必须包进这把锁；它依赖单 worker 部署（与运行时状态同一前提）。

### 事件溯源

事件是权威。`EventStore.active_events()`（当前活动分支）与 `branch_path()` 共同决定状态与**资产继承**；`RuntimeAssets.rebuild(store)` 是从事件重建场景资产索引的指定入口、**不落库**（`domain/game/assets.py`）。生产侧的调用点只有一处：`GameRuntime._current_background`（#56），解析顺序是**事件索引优先、剧本槽位兜底**——槽位是 Stage2 离线预生成的图（那时还没有 `asset_ready` 事件），运行期配图必须压过它，否则续写阶段的实时图永远显示不出来。

续写（Stage3）**没有目标、没有轮次上限、没有自动结局**：`stage3_goals_set` / `stage3_goal_achieved` 已停止写入（枚举与投影仅为历史会话保留读兼容），`stage3_rounds` 已删除。运行时每轮在 NPC 反应之后、导演出选项之前写一条 `world_chronicle {round, text, present, location_key, covers_event_id}` 增量事件；`domain/game/chronicle.py::derive_chronicle(events, viewer=…)` 拼接全量/限知视图，角色只拿 `viewer` 限知视角，全量只给 staff/教师。结束只由客户端 `exit_game`（关闭本局）或教师结束课堂触发，不产生叙事结局。

角色记忆同理：`CharacterMemory`（`working_memory` / `personal_log` / `rejected`）是**有界读取窗口**（最近 10 条），由 `proposal` / `character_speech` / `character_created` 事件折叠重建；`RuntimeState.plot_log` / `speech_log` 各留最近 50 条。快照只是缓存：每分支只保留最近 20 个命令快照（`kind='rollback'` 全留），删旧快照只增加重放量、不改变结果。角色可见叙事摘要由 `plot_entries_for(viewer)` 从活动分支事件派生，`view_my_memory` / `view_plot_log` 是唯一读取口；`plot_context` / `current_direction` 仍是 write-only 的全局广播，不得直接暴露。

**实例记忆存储**（stage3-chronicle-redesign §1.3）：`domain/game/memory.py` 的 `MemoryStore` 端口 + `infrastructure/memory_store.py` 的文件系统实现（`WENJING_MEMORY_BACKEND=fs` 启用，默认 `null` = 纯进程内事件派生）。实例目录 `<root>/<session_id>/`：`events.jsonl` 是事件流镜像（按 `(branch_id, event_id)` 增量去重、`O_APPEND`+`fsync`、崩溃残行下次打开时隔断），`instance.lock` 是 `O_CREAT|O_EXCL` 单写者锁（持锁进程已死时按 PID 接管，仅 POSIX；Windows 上 `os.kill(pid,0)` 会终止进程，故保守拒绝接管，空锁按年龄回收），`memory/<character>.json` 是角色记忆派生缓存（命令收尾刷新，失败只记日志）。事件仍是唯一权威；目录里的东西删掉可从事件流重建。`CharacterInstance` = agent + 实例记忆句柄，`CharacterFactory` 是角色唯一创建路径（剧本角色与运行期新增角色都走它）。

运行期配图的**持久台账**在 `asset_jobs`（#57）：每会话生图上限与崩溃恢复都建在它上面，因为 `assets` 行的归属必须落在**剧本**名下（写 `session_id` 会让 `AssetAccessService` 改按会话鉴权，跨会话缓存复用直接 403）。`Container.open()` 会调 `SessionApplication.recover_asset_jobs()`——先把上次进程留下的 `pending` 票据判死，再把 TTL 内的在途任务重排。

### 运行期流式与音频

事件流里**只有最终完整文本**；`stream_*` 与 `audio_*` 是 WS 瞬态消息，没有 `seq`、不进 outbox，断线重连靠 `resync` 补完整消息而非逐字回放。

出口全是**连接级**，在 `controllers/routes.py` 的 `_handle` 里建；运行时只认一个 `speech_sink` 参数，并不知道 tee 的存在：

```
LLM token 流 ──StreamTee──┬─ StreamChannel → JSON 帧 `stream_*`（逐段，有界缓冲 + drop-oldest）
                          └─ 分句器 → TtsSynthesizer → AudioTrackChannel → 控制帧 + 二进制帧
```

分句在 `domain/game/streaming.py`（`SENTENCE_ENDINGS`），合成与音色映射在 `domain/game/tts.py`，识别在 `domain/game/asr.py`。

四条读单个文件看不出来的约束：

- **一条命令结束时 `AudioTrackChannel` 只 `flush` 不 `aclose`**。它是连接级的，每条命令都关会让第二条命令起的音频全被静默吞掉（现象：只有第一个角色有声音）。
- **二进制帧不带 `track_id`**，「帧归谁」全靠「一条音轨的帧在流上连续」这条不变量；服务端由 `TtsSynthesizer` 保证同轨 start/chunk/end 之间没有 `await`。
- **轨的粒度是「句」不是「发言」**。ADR §11 说的「按 speaker 各推一条流」指的是**不混音**，实现落成一句一轨（合成按句排队、每句合完即开轨），同一角色的 N 句就是 N 条轨，靠 per-speaker 链保序——换来 TTFT 等于「首句」而非「整段发言」。
- **`null` provider 下音频静默跳过**（收到空字节就不开轨），字幕照滚。无 key 的开发环境没有配音**不是故障**。

**barge-in 的实质只在客户端**：服务端 `cancel_audio` 只能丢掉尚未发出的帧——命令串行且 WS 接收循环在命令期间不读新消息，客户端发不出「生成中途」的取消。真正的「停」是前端 `stopAll()`（`<audio>.pause()`）。

**ASR 只转文本、不落音频**：`POST /api/sessions/{id}/transcribe` 在请求内用完即弃，不写对象存储、不进事件流，日志里只有字节数；识别结果由前端当普通 `free_input` 提交——命令端点仍是唯一游戏输入入口，语音不开旁路。

流式与音频决策的「实现注记」（2026-10-01）记着决策落地时澄清的地方，相关措辞与正文有出入时以注记为准（原始 ADR 已删除，见 git 历史）。

### 剧本生成 workflow

```
collect_materials → verify_materials → [materials_gate] → divide_events
  → design_characters ⇉ Send 扇出 N → design_one_character×N → merge_characters(join)
  → [pre_write_gate] → write_script → write_dialogue → final_audit
  → design_exploration → design_assets → [final_gate] → END
  （reject 带打回意见回上游重做，不设轮次上限）
```

打回没有业务轮次上限，防死循环只靠 `WorkflowRunner` 的图递归上限
（`WORKFLOW_RECURSION_LIMIT = 10000`；LangGraph 默认 25 会在多轮打回后提前抛
`GraphRecursionError`）。这条是兜底护栏，不是「还能重试几次」的业务预算。

`design_exploration` 在总审通过后从主场景派生 `ExplorationMap`（起点、地点、在场、
画面摘要），让所有新剧本都带探索地图；它也是后续删除旧剧本线性路径的前置条件。

配图在总审**之后**（#48 选项 A：不为一篇可能被打回的剧本付图片钱）；教师对配图槽位的四操作（重新生成/检索替换/上传/删除）经 `GateEdits.asset_ops` 随 final_gate 的 approve 生效（#49）——reject 路径忽略 ops，重写后 design_assets 重跑。

**配图一致性靠「头像先行 + 参考图」**：`design_assets` 先生成人物头像，再用 `SceneDesigner.asset_bytes` 取回头像字节，作为该角色所在场景/分支的 `reference_images` 下发给生图 provider（Ark `image`，base64 data URL，最多 10 张）；prompt 末尾追加「外观须与参考图一致」。运行期 Stage3 配图同样带参考图：引擎从剧本包的 `avatar_asset` 取在场角色头像 id（`SceneAssetIntent.reference_asset_ids`），调度器读字节后下发。`Appearance` 的 `gender`/`age` 是硬锚点（七要素），画师层渲染时排在五官之前。带参考图的去重键追加 `+ref` 后缀——同一描述带不带参考图是两种产出。设计见 `docs/design/image-generation-quality.md`。

教师闸门靠 `interrupt()` 暂停、`Command(resume=directives)` 恢复，**必须**有 AsyncPostgresSaver checkpointer 才启用。注意这层耦合：没有 `WENJING_LLM_API_KEY` 就没有 checkpointer，`workflow_enabled=False`、闸门不启用，生成退回旧确定性合成路径（仅测试/E2E 依赖，随 #33 退役）——生产链路只走 workflow + 真实 LLM。

## 陷阱与约定

**`make test` 会清空所连的库**：集成测试结束 `drop_all` 全部业务表并删 `alembic_version`（`tests/conftest.py`），交还空库。别对想留数据的库跑；跑了补 `make migrate && make seed`。手动起后端**不会**自动迁移（只有生产入口默认 `alembic upgrade head`）。

**`make test` 在 `WENJING_LLM_API_KEY` 有值时会打到真实 provider**（`test_api_sessions.py` 的 `client` fixture 经 `get_container()` → `_build_agent_llm()` 拿到真家伙），被限流时表现为「整套跑 25 分钟像卡住」，实为外部调用排队而非死锁。要快跑或让结果确定就 `WENJING_LLM_API_KEY= make test`——置空走 `DeterministicAgentLLM`，同一套用例 70 秒跑完。

**外部依赖不可用时集成测试静默 skip**，**全绿不代表跑过**。两类：PostgreSQL（`test_db_event_store`、`test_migrations`、`test_full_flow`、`test_api_sessions` 等）→ 先 `make db-up && make migrate`；MinIO（`test_media_storage.py` 的对象存储集成用例）→ 先 `make media-up`。只有 MinIO 这类有 `WENJING_TEST_MINIO=1` 把静默跳过变成硬失败（CI 用它）；PG 那类没有这个开关，库没起就是纯绿。

**后端必须单 worker**：会话运行时、WS outbox、在途生成都是进程内存 / asyncio 任务状态。多 worker 或多副本的后果与运维细节见 `README.md` 生产部署一节。

**新增错误码要同时登记五处**，漏任何一处都不报错、只静默降级（errx 用法见 `infrastructure/errx/__init__.py`）：

1. `infrastructure/errx/codes.py`：整数常量（按模块分段，段内连续）
2. 同文件 `register_all()`：`register(CODE, "模板 {reason}", is_affect_stability=…)`——模板用于服务端日志与服务端消息。注意 `is_affect_stability` 只是挂在 `Error` 上的标记，**当前无人消费**，它**不是**对外 `retryable` 的来源
3. `contracts/errors.py::STABLE_CODES`：`"DOMAIN_NAME": (ErrorDomain.X, retryable)`——**只有 `retryable` 是 load-bearing 的**。元组里的 `ErrorDomain.X` 当前被丢弃（`envelope_for` 写的是 `_domain, retryable = stable_code(...)`，domain 改由码名前缀现推），所以域写错**不报错、只静默失效**；真正会炸的是**前缀不是合法 `ErrorDomain` 值**——`ErrorDomain("<prefix>")` 抛 `ValueError`
4. `infrastructure/diagnostics/errors.py::_CODE_MAP`：整数码 → 稳定码名。**漏了对外信封回落 `INTERNAL_ERROR`**
5. 同文件 `safe_message`：整数码 → 用户可见中文。**漏了用户只看到「服务内部错误」**

**改代码里的 prompt 文本对已 seed 的库不生效**：system/准则/判据类文案存 `prompts` 表，键为 `(stage, node, version, section)`，代码默认在 `domain/prompts/defaults.py`，DB 无行/禁用/异常时回退默认。DB 覆盖行按 version 匹配，所以**必须升 `VERSION`** 才会落到新键上并回退到新默认；`make seed` 只幂等补新行，不覆盖已启用行。字段类型说明类文本（`_OUTPUT_CONTRACT`）留在代码、不落库。

**运行期 Agent prompt 是代码内联的，不走 `prompts` 表**：改 `domain/agents/prompting.py` 的 `build_*_prompt` / 常量即生效，不要 `make seed`、不要升 `VERSION`。所有 prompt 经 `PromptBundle{system,user,version}` 组装：system 稳定、动态内容只进 user；槽位（来源/可见性/上限/降级）声明在 `*_SLOTS`，system 指纹由 `tests/test_prompt_bundles.py` 钉住。Full 清单与「查阅/试验/更新」流程见 `docs/prompts/runtime-agents.md`。三条易踩的耦合：`tests/conftest.py::FakeLLMService` 扫 system+user 全文，按「验证 Agent」「世界构建 Agent」「导演 Agent」路由；`fake.py::DeterministicAgentLLM` 只看最后一条 user，识别 `react` 与「验证 Agent」，Director/WorldBuilder 在确定性模式下解析失败后走兜底。改标记必须同步两处与测试；`choose_option` 的文案会写进 `PlayerAction.text` 与 `player_action` 事件，NPC 反应/目标判定/回放都据此；Director 的 `dimension` 只记日志、不强校验（`director_dimension_thin`）。

**契约单源四处，但只有三处受保护**：`backend/app/contracts/`（Pydantic，唯一事实源）→ `contracts/fixtures/`（**手工维护的样例载荷**，不是生成物）→ `contracts/jsonschema/`（`scripts/export_contracts.py` 的导出产物）→ `frontend/src/lib/contracts/types.ts`（手工镜像）。改契约后跑 `cd backend && uv run python -m scripts.export_contracts`；`tests/test_contracts.py` 断言导出与 fixtures 都不过期，但**完全不管 `types.ts`**——它没有生成器，得自己同步。流程见 `docs/contract-change-process.md`。

**测试约定**：`asyncio_mode = "auto"`（async 测试不用加 `@pytest.mark.asyncio`）；HTTP 打桩用 `httpx.MockTransport`；联网 / 真实 LLM 测试按 env 门控（无 key `pytest.skip`，开关如 `WENJING_TEST_IMAGE_SEARCH=1`）；`caplog` 在整套跑时不可靠，测日志用 monkeypatch 把模块 `logger` 换成自建 probe（见 `tests/test_websearch.py::_ProbeLogger`）。

**单次 LLM 调用的超时与重试**（#65）：`llm_timeout_seconds`（缺省 240）是**整次** non-streaming 调用的预算，流式另有 `STREAM_IDLE_TIMEOUT_CAP = 150.0` 封顶相邻 chunk 的空闲间隔——**调大前者不会顺带拉长后者**。超时单列 `LLM_TIMEOUT`（4004），只重试超时（默认 1 次、指数退避 2s，置 `llm_timeout_retries=0` 可关），provider 报错不重试。流式**只在还没交出任何一片时**才重试，守卫是「是否 yield 过」而非「可见文本段数」——工具分片的 `content` 为空，只数文本会漏判，重开一条流会让消费端把同一段工具参数累加两遍。

**超时/失败异常的措辞一律走 `errx.exc_reason`（`类型: 消息`）**，不要用 `str(e)`：`str(TimeoutError())` 是空串，日志与对外信封会一起丢掉现场。同理，`errx.Error` 已被 `domain/` 包过的地方（如 `agents/character.py`）要 `except Error: raise`——再包一层会把码抹平成 `LLM_CALL_FAILED`，上层就看不出该调超时还是该换 key。

**契约 payload 必须经 `SessionApplication._engine_payload` 翻译到引擎**：它是契约命令 → 运行时 payload 的唯一翻译点。新增带参 `CommandKind` 时忘了加分支会被静默丢成 `{}`——`switch_scene` 曾因此永远拿不到 `scene_key`、换景命令在 REST/WS 上全部失效（`tests/test_command_payloads.py` 钉住映射）。

**游戏输入只有 REST `POST /api/sessions/{id}/commands` 这一个入口**（`contracts/commands.py` 的模块 docstring 这么写），语音、WS 都只是它的包装。请求体不合 `PlayerCommand` 时返回 `PROTOCOL_MALFORMED_MESSAGE` 信封（400），不是裸 500——`pydantic.ValidationError` 不在 `except WJError` 的作用域内，新增 `model_validate` 时记得翻译（#66）。

**`LLMService` 端口有四条通道**，改 agent/LLM 时别只改一条：`chat` / `chat_with_tools` / `astream`（只吐可见文本）/ `astream_with_tools`（`StreamChunk`，`content` 与 `tool_calls` 是**两条独立通道**，都照发）。忽略 `tool_call_chunks` 指的是「不把它当可见文本下发」，不是不产出——LangGraph 的工具节点靠它组装 tool_calls，丢掉工具轮永不触发。

**配置一律走 `infrastructure/config.py`**（pydantic-settings，env 前缀 `WENJING_`）；完整可选项见 `backend/.env.example`，provider 选 `null` 时对应端口是安全空实现。

## Agent skills

- Issue tracker：GitHub Issues，用 `gh` CLI。见 `docs/agents/issue-tracker.md`。
- Triage labels：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。
- Domain docs：单上下文布局，`CONTEXT.md` 在仓库根。见 `docs/agents/domain.md`。