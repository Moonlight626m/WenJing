# jubensha-ai 实现分析（供 WenJing 参考对照）

- 调研对象：<https://github.com/JianWang97/jubensha-ai>
- 调研 commit：`d935e8b0a9bc73924fef35a95675a38c51694985`（2026-10-14 浅克隆）
- 本报告所有论断均落到源码路径；仓库没有实现的点明确写「未实现/未见」。路径均相对仓库根；行为引用以 `backend/` 为主。

## 一、项目概览与技术栈

「全 AI 剧本杀」：所有角色由 LLM 扮演，游戏全自动推进（无真人玩家实时参与，真人只看戏/投票结算），含剧本生成、AI 对话式剧本编辑、TTS、文生图。

| 维度 | jubensha-ai | 备注 |
|------|-------------|------|
| 后端 | Python 3.13 + FastAPI + uv，自主 asyncio 循环（**非 LangGraph**） | `backend/pyproject.toml`；`langchain>=0.1.0` 仅作为可选 LLM provider（`src/services/llm_service.py:249`） |
| 前端 | Next.js Pages Router + React + Zustand + Radix/shadcn + Tailwind | `frontend/package.json`，`frontend/src/stores/` |
| 数据库 | PostgreSQL + SQLAlchemy + Alembic（无 ORM 之外的存储层抽象，仓库模式手写） | `backend/src/db/migrations/versions/` 3 个迁移 |
| 对象存储 | 本地目录 / MinIO 双模式（`FILE_STORAGE=dir`） | `backend/src/core/storage.py:43,58`（与 WenJing 同选型） |
| LLM | 自建 `BaseLLMService` 抽象（OpenAI 兼容 + LangChain 两个 provider），`get_llm_service()` 全局单例 | `backend/src/services/llm_service.py:86,105,249,391` |
| TTS | MiniMax / CosyVoice 2 本地部署，provider 切换 | `backend/src/services/{minimax_service,cosyvoice_service}.py` |
| 文生图 | MiniMax / ComfyUI（本地 workflow JSON） | `backend/src/agents/../services/{image_generation_service,comfyui_service}.py` |
| 鉴权 | JWT + FastAPI 依赖注入中间件 | `backend/src/core/auth_middleware.py` |
| 计费/配额 | **未实现**。`LLMResponse.usage` 只透传但没有消费点（`src/services/llm_service.py:27,151`），未见任何配额/计费逻辑 | — |
| 单 worker 约束 | 全部会话状态在进程内存（`GameWebSocketServer.sessions` 字典），无 outbox/checkpointer | `src/core/websocket_server.py:1292` |

## 二、剧本生成流程

**没有状态机/graph，没有人工审校闸门**。是一个单 Agent ReAct 循环：`思考 → 调工具 → 工具内校验+落库 → 观察作为下条 user 消息回灌 → 再思考`，直到调 `finish` 或达到 `max_iterations=15`（`src/agents/script_generation_agent.py:137`）。

- 六个有序步骤即六个工具：`save_script_info / save_background_story / save_characters / save_locations / save_evidence / save_game_phases`，外加 `finish`（`script_generation_agent.py:19-36`）。每个工具执行成功即**独立事务落库**，失败则把错误文本作为 observation 回给 LLM 让它自我修正——这是它「被打回怎么重试」的全部答案：**没有剧本级打回+重写循环**，校验粒度是单次工具调用的字段/规则校验（如「必须恰好 1 名凶手」「证据至少 5 条」「发现地点必须在已有场景里」，`script_generation_agent.py:560-620`），LLM 修改参数重调即可。
- 步骤完成度由 `completed_steps` 列表追踪，`REQUIRED_STEPS` 缺失时 `finish` 失败（`script_generation_agent.py:27,637`）；`game_phases` 缺失时自动补默认六阶段，保证剧本可直接游玩（`script_generation_agent.py:673-694`）。
- **一致性上下文**是手工摘要而非图状态：`_context` dict 存已建角色/场景名，每轮回灌 `【已确定角色】【已创建场景】`（`script_generation_agent.py:512-521`）。
- provider 不支持原生工具调用时**降级为 JSON 行动模式**：让模型输出 `{"action": ..., "arguments": ...}`，手工剥离 markdown 代码块 + 平衡括号扫描解析（`script_generation_agent.py:86-88,396-411`）。所有结构化输出路径都有这个双通道兜底（角色 agent 同样，见下）。
- 另有一条与 Agent 无关的旧确定性路径：`src/services/script_generation_service.py` 用一次性 prompt + `_strip_json_markdown` 提 JSON 直接落库（`generate_script_info` / `generate_and_save_content`），由 REST 端点 `POST /api/scripts/generate-info|generate-content` 调用（`src/api/routes/script_routes.py:20-51`）。README 主打的是 WS 上的 Agent 路径，这条是轻量接口。
- 剧本编辑是第二个 ReAct Agent（`src/agents/script_editing_agent.py`，760 行）：工具是**真实编辑操作**（`add/update/delete_character`、`add/update/delete_game_phase`、`bind_character_voice` 等），由 `ScriptEditorService` 执行，计划模式先把指令解析成 `EditInstruction` 列表不落库、执行模式才落库（`src/api/routes/script_editor_routes.py:20-30`）。同一剧本的编辑用 per-script `asyncio.Lock` 串行化（`websocket_server.py:1294`）。

## 三、多角色 Agent 编排

角色 agent 的分层相当干净，明显参照 hello-agents chapter15 AI Town 教程（代码注释多处自我声明，`character_agent.py:1-17`）：

- **三层分离**：
  1. `CharacterIdentity`（`src/agents/character_identity.py`）：system prompt = 纯「我是谁」（背景/秘密/目标/性格 + 8 条表达纪律），游戏全程不变；凶手/受害者只追加一段通用行为备注（凶手可以说谎、隐瞒证据），不含阶段策略。
  2. `CharacterMemory`（`src/agents/character_memory.py`）：进程内存中分层私有记忆——`working_memory`（deque(maxlen=30) 最近公开对话）、`personal_log`（私有事件日志，容量 60，超出按 importance 升序淘汰）、`suspicion_map`（怀疑度 0.0-1.0，被点名 +0.05 的简单启发式，`character_agent.py:238-247`）、`known_evidence`（自己搜到且未公开的证据——**知识边界就落在这里**：搜证结果只写发现者的 memory，未公开前其他角色不可见，`character_agent.py:250-260`）。
  3. `PhaseDirector`（`src/agents/phase_director.py`）：无状态纯函数，按 `GamePhaseEnum` 注入阶段任务指令（八阶段各有硬编码 prompt 大段）+ 阶段工具说明 + 记忆上下文 + 游戏状态快照。
- **发言与行动双通道**：有工具阶段（搜证/调查/讨论/投票）原生 tool calling 完成 `search_location / ask_question / reveal_evidence / cast_vote`（`src/agents/agent_tools.py`），公开发言走回复正文；模型不回工具调用时回退旧版 JSON 契约（`AgentResponse` 的 `say/action/reveal_evidence/vote/emotion`，`character_agent.py:55-110`），最坏降级纯文本，**绝不向游戏循环抛异常**（`character_agent.py:158-162`）。工具参数还带权限校验：`reveal_evidence` 只能公开自己 `known_evidence` 里的证据（`phase_director.py:160-170` 文案约束）。
- **提议→验证/裁判机制：未见**。没有 critic/auditor agent，投票结果直接由 `VotingManager.get_most_voted()` 数票定胜负（`src/core/voting_manager.py:14-33`）。唯一的「结构性约束」是生成与投票用工具调用而非自由文本。
- **主持人 GM Agent**（`src/agents/gm_agent.py`）：动态规划阶段序列——分析角色数/证据量/场景数生成 `PhaseStep` 列表（LLM 驱动，失败回退规则化默认计划，`gm_agent.py:42-100`：证据≥8 或角色≥5 就插第二轮搜证），每阶段带 `max_turns`、`gm_instructions`（注入 PhaseDirector）和旁白公告。
- **谁来发言**由 `ConversationFlowController`（`src/core/conversation_flow_controller.py`）管：按阶段策略选下一个发言者（自我介绍按顺序、调查/讨论用 LLM 判断），外层 `run_phase` 再加「同一角色连续发言≥2 就强制换人」的保险（`game_engine.py:778-788`）。
- `CharacterAgentManager` 注入共享 LLM 单例、广播 `observe()`（`character_agent.py` 过程见上）。

## 四、游戏会话的前后端交互

**WebSocket 全包，REST 仅管理面**。会话内一切（开始游戏、发言、编辑、生成、历史回看、后台模式）都是 WS 消息，16 个 `MessageHandler` 按消息 type 字典分发（`websocket_server.py:1298-1315`）；REST 只有 auth/user/script CRUD/TTS 历史/开始恢复游戏（`src/api/routes/game_routes.py`、`game_history_routes.py:76`）。

- **生成是异步后台任务**：`start_script_generation` → `asyncio.create_task(run_and_finalize())`，事件实时广播 `script_generation_event`（`websocket_server.py:380-483`）。「通知」就是广播本身——**没有持久化任务表**，生成状态 `generation_status` 与事件日志 `generation_events` 都挂在内存 `GameSession` 对象上（`websocket_server.py:85-89`）。
- **记号式断线恢复（内存版）**：
  - 生成侧：事件日志上限 500 条、状态查询消息 `get_script_generation_state` 拿 `{status, events}` 全量回放（`websocket_server.py:515-534`）；事件 ID 自增，游戏侧 `fetch_history` 按 `from_event_id` 增量拉（`websocket_server.py:318-338`，`game_engine.get_history` 注释明说「用于前端回看，不涉及断线状态恢复」）。
  - 会话侧：WS 连接 URL 带 `user_id`（token 解出）+ `script_id`，服务端 `create_or_resume_session` 自动复用同一用户的旧会话（`websocket_server.py:1348-1355`）；前端 3 秒定时重连（`frontend/src/stores/websocketStore.ts:419-426`）。
  - **后台模式**：`set_background_mode` 打开后，所有客户端断连也**不清理**游戏循环，重连检测 `background_mode && clients 为空` 后续跑（`websocket_server.py:1374-1420,1436-1440`）。进程重启则全部丢失（未实现跨进程恢复）。
- **游戏主循环**是 `asyncio` while 循环：`run_phase`（选人→agent.respond→回调广播）→ 广播 `game_state_update/public_chat_update` → 按阶段表 sleep 5-10 秒（切成 1 秒小片以便随时叫停）→ `next_phase` → GMAgent 旁白（`websocket_server.py:724-900`）。**这就是「长任务」的全部形态：任务在后台 task 里跑，周期性广播，玩家◔位看进度**。
- **流式输出：逐条不逐字**。角色发言以「整段 action」为单位回调广播并**同步等 TTS**（先 `generate_character_tts` 拿到 URL 再广播 `ai_action`，`websocket_server.py:826-870`）；`split_think_tags` 把 `<think>` 拆成 reasoning/content 片段透出（生成 agent 用了，`script_generation_agent.py:226-230`），但游戏内发言不支持逐字流。所有二进制音频走 HTTP（`tts_file_url`），不占 WS。
- **持久化严重偏科**：游戏事件落库的**只有 TTS 事件**（`game_tts_manager._save_tts_event_to_db` 写 `game_events` 表 event_type="tts"，`game_tts_manager.py:233-277`）与 tts_event_service 同理；对话/推理/阶段切换的 `add_event`/`add_public_chat` 只进内存列表（5000 条容量裁剪，`game_engine.py:552-570`），**事件溯源只到「服务重启前」**。`game_events` 表反而被 game history 页面当事实读取（`game_history_service.py:82-86`）——即「无 TTS 的对局在历史里几乎没有内容」，这是个值得引以为戒的裂缝。
- 会话恢复的 REST 端点 `resume_game` 也只是把 `PAUSED→STARTED` 后**构造一个假 WS URL**（硬编码 `ws://localhost:8000/ws?script_id=...`，状态不含运行中信息）（`game_history_service.py:168-175`），与 register 时 `session_connected` 里带的 `active_game`（当前阶段+game_state，`websocket_server.py:1394-1408`）相比是半成品。

## 五、对 WenJing 的参考点

WenJing 现行做法（据 AGENTS.md 与 ADR）：LangGraph workflow + 三道教师闸门（interrupt/resume）、事件溯源 `EventStore` + Postgres outbox、多 agent 提议/验证循环、REST 命令唯一入口 + WS 瞬态流（`stream_/audio_` 不入流，重连靠 `resync`）、`asset_jobs` 台账管生图、`GameSessionStore` 深模块统一 CAS 事务。

1. **工具内校验即「闸门」——jubensha-ai 把全部质量闸门压进工具执行函数**（`script_generation_agent.py:560-620`），校验失败当 observation 回灌自我修正。这与 WenJing 的 sustain 闸门是同一思想在更小粒度的落地，但**它完全没有剧本级整体审校**（呼应 WenJing 的 final_audit），也没有 deny 后重写的预算管理。结论：单条工具级校验 WenJing 大概率已有等价物，真正可借鉴的是「校验失败的 observation 原文回灌让 LLM 修」这个零成本的错误反馈拼写。
2. **生成事件日志 + 状态查询消息的重连拼写（`MAX_EVENT_LOG=500` + `get_script_generation_state`）**与 WenJing 的「瞬态不入流、`resync` 补完整消息」思路一致，但 jubensha-ai 版实现薄：日志在内存、上限裁剪后旧事件拿不回来。WenJing 的 outbox+seq 方案**更强**，此处无需学习，反而验证了 WenJing 设计的必要性（jubensha-ai 自己也承认 `get_history` 「不涉及断线状态恢复」，`game_engine.py:115`）。
3. **角色知识边界走「私有记忆结构」而非运行期访问控制**：`known_evidence` 只写发现者 memory、工具层约束「只能公开自己掌握的证据」。WenJing 的角色知识边界如果目前只靠 prompt 约束，jubensha-ai 的「私有仓 + 显式公开动作（reveal_evidence 是一个工具调用而非自然文本）」是值得借鉴的机制——**公开必须是显式动作，而非模型在叙述里顺嘴说出**。
4. **身份/记忆/阶段任务三层分离 + PhaseDirector 纯函数化**是比 WenJing 现行角色 agent 结构更干净的一种切法：system prompt 全程恒定（identity 层可被 WenJing 的 prompts 表机制直接管理），阶段指令与记忆上下文拼在 user message。WenJing 若在续写/演绎阶段觉得 prompt 拼装散，可参照此三切。
5. **后台生成 + 阶段化 game loop 后台 task 模式**：jubensha-ai 把「生成/游戏」都做成 asyncio 后台任务、事件广播、玩家端看流水。WenJing 的命令串行 + 事件流是等价目标，但 jubensha-ai 的「后台模式」语义（断连不清场、重连续跑当前回合）在产品体验上是个好概念，值得 WenJing 考虑对运行中会话提供同等语义（当前依赖重连 resync，已有基础）。
6. **jubensha-ai 明显更弱处**（避免误学）：事件只在 TTS 时落库，服务重启即失去全部游戏状态，`game_events` 表与内存事件双轨不一致；无提议/验证、无整体审校；中断恢复靠假 URL 的 `resume_game`（`game_history_service.py:168-175`）；无配额/成本控制。WenJing 的事件溯源、闸门、asset_jobs 上限等都**领先于它**，这些不要倒退。
