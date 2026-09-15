# 文境核心 MVP — 实现规划 Todo

> 依据 GitHub issues #1–#14（spec: 交付可投入真实试用的文境核心 MVP）。
> 每项标注对应 issue、工程落点（代码/迁移/契约）、验收要点与阻塞关系。
> 原则：contracts-first · blockers-first · fake-backed vertical slice · 生产化加固验收。

## 依赖 DAG（推进顺序）

```
第一波 · 地基（无外部阻塞，可并行）
  [#2] Shared Contracts 冻结（全量）     ← 唯一立即开始，其余全依赖它
  [#6] 前端 mock 全流程（mock server）   ← 只依赖 #2 fixtures，可并行开发

第二波 · 依赖 #2，专业向并行
  [#3] 诊断基建（日志/错误/health/metrics）
  [#4] 持久化基线（迁移 + commands/event_branches + 事务）
  [#7] GameRuntime command/step 重构     ← 依赖既有 core 迁移
  [#9] 课文导入/体裁判断/原文证据模型

第三波 · 依赖第二波
  [#8] 回放/幂等/分支回溯（依赖 #7）
  [#10] 安全开放网络 RAG（依赖 #2）
  [#11] Schema-first Stage1 生成（依赖 #9）

第四波 · 汇聚成竖切
  [#5] fake-backed 后端竖切（依赖 #2 #3 #4，#11 前以 fake adapter 成立）

第五波 · 真实集成 + 质量
  [#12] 真实核心集成端到端（依赖 #5 #6 #7 #8 #10 #11）
  [#13] 生产化加固故障注入（依赖 #12）
  [#14] Gold Set 内容质量问题（依赖 #12）
```

## 第一波 · 地基

### [#2] 冻结核心领域与协议契约（Shared Contracts）✅ 已完成（2026-08-27）

工程落点：`contracts/`（JSON fixtures 单源）+ `backend/app/contracts/` + `frontend/src/lib/contracts/`（两端语言类型）。

- [x] 版本化类型：MaterialInput/Material、EvidenceRef（原文区间/段落 + 网络来源）、ScriptPackage、
      PlayerCommand、DomainEvent（session/branch/sequence/causation/correlation/schema_version）、
      RuntimeState、GameSnapshot、RuntimeUpdate、ErrorEnvelope（error_id/code/message/retryable/details）
      —— 落点 `backend/app/contracts/{base,enums,material,script,commands,events,runtime,errors,dto}.py`
- [x] 命令类型集合（7 种 CommandKind）+ 每阶段 allowed_commands（enums.ALLOWED_COMMANDS）
- [x] 领域模型 ↔ REST/WS DTO 分离，显式 mapper（contracts/dto.py：interaction_to_payload / error_to_payload / client_message_adapter）
- [x] 前后端共享同一份 `contracts/fixtures/*.json`（8 个样例：材料输入/材料/剧本包/命令/事件/运行态/错误/信封）
      + `contracts/jsonschema/*.schema.json` 由 `backend/scripts/export_contracts.py` 导出
- [x] 错误码域覆盖 INPUT/CONTENT/SEARCH/LLM/GAME/SESSION/PERSISTENCE/PROTOCOL/INTERNAL
      （errors.STABLE_CODES 登记 24 个稳定码；code 必须以 domain 为前缀，模型级校验）
- [x] 契约一致性测试：`backend/tests/test_contracts.py`（22 例：fixture 严格校验/schema 不过期/
      零基础设施依赖导入断言/payload 判别/mapper 往返）；前端 TS 镜像经 tsc --noEmit 验证
- [x] 契约变更流程记录：`docs/contract-change-process.md`（breaking change ≥2 模块 owner review）

### [#6] 前端 mock 全流程 ✅ 已完成（2026-09-05，浏览器 E2E 除外）

- [x] 导入页（/import）：粘贴 + .txt/.md 上传（扩展名校验、字数显示）、
      ingestion 校验错误内联展示（INPUT 域）；原文分析结果渲染
      （体裁标签/人物含性格/场景/按序关键事件）
- [x] 生成进度：导入页内联四阶段（体裁判断/网络研究/生成/校验）进度提示；
      GET status 的 GenerationProgress 已接入；真实 LLM 模式下提示长耗时
      （deepseek Stage1 实测 ~103s，fetch 无超时直接等待）
- [x] 选角页（/roles）：角色卡（简介/性格标签/可扮演标记）、REST select_role、
      刷新后回退仅列角色名（ScriptPackage 无 GET 端点，暂从内存 store 取）
- [x] 游戏页（/game）：消息流（叙事 markdown/角色发言气泡/系统胶囊，auto-scroll）
      + 三输入模式交互卡（options/free_input/options_with_fallback）
      + enter_stage3/confirm_ending/exit_game 附加命令按钮
- [x] 命令 pending 态：单飞行 + 同 command_id 幂等重发（120s 窗口重试一次，
      超时报错并提示刷新恢复）；服务端 seq 消息按 `seq:type` 去重
- [x] 刷新恢复：localStorage 最近会话（useSyncExternalStore 订阅）+ 按阶段路由
      （init→导入、stage1_complete→选角、stage2+→游戏）；
      WS 指数退避重连（0.5s 起 15s 封顶 ×12），重连后 session_init 权威重建
      + resync 按本地确认水位补发；confirm_messages 持续修剪服务端 outbox
- [x] 回溯：时间线 select 目标 + 二次确认 → rollback_to_event
- [x] 错误按域呈现：input/content/llm 内联 + toast；session/game/protocol toast
      （ErrorEnvelope 的 code+message，网络不可达转译为友好文案）
- [x] 协议级验证（真实后端 WS，scripts 临时脚本实测）：session_init→resync 补发、
      命令→消息批次、幂等重发对账、新连接全量重建 —— 行为全部符合前端假设
- [ ] 浏览器测试覆盖核心流程：需要 Playwright 基建（依赖安装 + CI），随 infra 批次
- 注：mock server 决策 —— fake-backed 真后端（`WENJING_LLM_API_KEY= uvicorn`）
  即确定性 mock，不再单独维护 mock server；
  已知缺口：ScriptPackage / 角色简介无 REST 查询端点（刷新选角页只剩角色名），
  随 #12 联调时补 GET /api/sessions/{id}/script

## 第二波 · 专业向并行

### [#3] 建立统一诊断基础设施 ✅ 已完成（2026-08-27）

- [x] 结构化日志：`app/diagnostics/logging.py` —— 部署 JSON / 开发可读双 formatter；
      标准字段 request/session/command/generation/llm_call/correlation_id +
      duration_ms/error_code/retry_count
- [x] contextvars 关联 ID 传播：`app/diagnostics/context.py`（六类绑定 API）+ CorrelationFilter
      注入每条记录；HTTP 中间件每请求 reset/bind_request 并回写 X-Request-ID 头
- [x] 日志脱敏：api_key/prompt/raw_text/玩家输入等敏感键 → `<redacted>`；
      有测试断言敏感全文不落日志
- [x] errx 扩展：`app/diagnostics/errors.py` —— 整数码↔稳定码映射、error_id 生成、
      envelope_for() 统一出口；cause/stack 仅服务端日志（与 error_id 同条可对账）、
      安全 message 白名单翻译，未映射码回落 INTERNAL_ERROR(retryable)
- [x] `/health/live` + `/health/ready`：ready 检查 database_url 配置与 PostgreSQL 可达，
      瞬时 LLM/搜索不可用不影响就绪；`/health` 保留兼容别名
- [x] `/metrics`：进程内注册表 `app/diagnostics/metrics.py`（Prometheus 文本子集），
      覆盖 requests/errors/ws_connections/command latency/db_tx_failures 计数
- [x] 测试：6 例诊断（脱敏/envelope 映射/error_id 定位服务端日志/关联字段注入）
      + 4 例 API（live/ready 双态/metrics 增量/WS 连接计增减）
- 注：生成成功率与 LLM token 指标的埋点随 #11/#12 接入管线时补全

### [#4] 建立正式持久化基线 ✅ 已完成（2026-08-27）

- [x] 补 `commands` 表（command_id PK/payload/status/result_event_id/kind/session FK）与
      `event_branches` 表（branch root/root_sequence/parent_branch/created_by_command）
      —— `backend/app/models/command.py`、`event_branch.py`
- [x] `events` 加 branch_id+sequence((branch_id,sequence) 唯一)/causation_id/correlation_id/schema_version；
      `snapshots` 加 schema_version；`sessions` 加 active_branch_id/head_event_id/version(乐观锁)
      —— 注：active_branch_id 为逻辑引用无库级 FK，避免与 branches.session_id 循环依赖
- [x] 真实 Alembic 迁移替换空 0001 + upgrade/downgrade 测试（`tests/test_migrations.py`：
      基线表存在性/events 关键列/(branch_id,sequence) 唯一约束/up-down-up 幂等环；
      PG 不可用时干净 skip，CI 接入后强制执行；连接探针带 5s 超时防黑洞挂起）
- [x] 生产建库路径不再依赖 create_all —— `db/factory.init_db` 已删除，Alembic 是唯一建库机制
- [x] PG 集成测试接入 CI —— 测试已就绪；CI workflow 随 infra 批次落地
- [x] 事务原子性测试（`tests/test_persistence_transactions.py`：命令+事件+head/version 同事务，
      commit 前注入失败零残留 / 全部同批可见 / 乐观锁版本拦截 / command_id 主键幂等闸）
- [x] 附带修复：session_id 强制 UUID 校验（旧 "s1" 字符串在真实 PG 下必炸的潜在坏路径）、
      flush 先登记确定性主分支再按分支连续 sequence 写入、alembic env.py 从 Settings 解析 URL

### [#7] GameRuntime command/step 重构 ✅ 已完成（2026-08-27）

- [x] `app/core/game_runtime.py`：start/submit/rollback/restore 接口；每次提交推进到稳定交互点或
      终态返回 StepResult（内部 RuntimeUpdate 形状，#5 Session 层映射契约）
- [x] 进度游标 beat_cursor、stage/phase、玩家角色、plot_log、角色记忆全部位于显式 `_RState`
      + `export_state()` 序列化投影（快照=状态；replay_from 为 #8 预留接缝）
- [x] RuntimeState 无 WebSocket/SQLAlchemy/LLM client —— 有源码级断言测试与纯 JSON 结构断言
- [x] command_id 幂等：重发返回首次结果 duplicate=True，零重复领域事件（测试断言事件计数不变）
- [x] 测试迁移到命令序列：`tests/test_game_runtime.py` 16 例（阶段序列/编排/提议验证/
      结局确认双出口/回溯恢复+重推进/溢出拒绝/allowed_commands 约束/可扮演角色校验）；
      **GameEngine.run() 与 game_engine.py 已删除**（未保留测试 adapter，一步到位）
- [x] allowed_commands 从 `contracts.enums.ALLOWED_COMMANDS` 单源派生（引擎侧无重复定义）
- [x] 附带修复：errx extra 值非 str 导致的格式化崩溃（统一 str 化）
- 注：Agent 构造仍注入 llm gateway（LLMService）；分支化回溯旧历史保留在 #8 实现

### [#9] 课文导入 / 体裁判断 / 原文证据模型 ✅ 已完成（2026-09-05）

- [x] 粘贴 + .txt/.md 上传校验（编码/空内容/大小/扩展名）；规范化 + 内容 hash
      —— `app/content/ingestion.py`：UTF-8→GB18030 解码、扩展名白名单、空/超长拦截、
      NFC+去 BOM+统一换行+压缩空行、SHA-256 content_hash
- [x] 叙事体裁判断：小说/叙事文/戏剧/人物故事通过；说明文/议论文/纯写景/诗歌返回 CONTENT_UNSUPPORTED_GENRE
      —— `app/content/genre.py`：确定性启发式分类（8 体裁全集，`contracts/content.py::SUPPORTED_GENRES` 单源）
- [x] 原文分析：人物/关系/场景/关键事件，关联原文字符区间/段落
      —— `app/content/analysis.py`：零 LLM 启发式提取（对白归属/称谓共现/地点时间标记/事件动词），
      每条结论附 OriginalEvidence（文档级 char 区间 + paragraph_index）
- [x] EvidenceRef 区分原文证据与网络补充
      —— `contracts/material.py::EvidenceRef`（original_text | web 判别）；分析侧只产出 OriginalEvidence，
      WebEvidence 留待 #10 RAG 侧产生
- [x] 同输入下 deterministic 一致 —— 纯函数启发式，零随机/零 LLM；测试断言两次输出逐字节一致
- 新增契约：`app/contracts/content.py`（GenreType/GenreClassification/CharacterMention/
      RelationshipEdge/SceneSetting/KeyEvent/TextAnalysis）+ `contracts/fixtures/text_analysis.json`
      + jsonschema 导出 + 前端 `types.ts` 镜像
- 新增错误码：errx CNT_UNSUPPORTED_GENRE(6001) + INP_*(7001–7004)，接入 diagnostics 稳定码映射
- 测试：`tests/test_content_pipeline.py`（导入校验/体裁 8 分类/分析坐标/证据判别/确定性）；
      契约测试新增 text_analysis 严格校验（48+ 例全绿）

## 第三波

### [#8] 运行时回放 / 命令幂等 / 分支回溯 ✅ 已完成（2026-09-05）

- [x] snapshot + active-branch 事件重放后与原 RuntimeState 一致（属性级断言）
      —— `game_runtime.replay_from(snapshot, events)`：快照提供记忆基线，按事件
      确定性重放 stage/beat_cursor/plot_log/player_role/stage3_round/ended
- [x] 非法 stage/命令返回稳定 GAME_* 错误；allowed_commands 生效（#7 已覆盖，
      本轮补「回溯目标不在活动路径 → GAME_ROLLBACK_TARGET_MISSING」）
- [x] 回溯：旧事件保留、新 active branch 从目标节点创建、head 更新
      —— `core/event.EventStore` 分支语义（`BranchMeta` 血缘链 / `branch_path` /
      `rollback_to` 建新分支不物理删除）；`game_runtime.rollback` 改用建分支
- [x] 回溯后后续命令只追加到新活动分支（测试断言新事件 branch_id == 新分支）
- [x] 快照与 branch/head 更新原子提交
      —— `db/branch.commit_rollback_branch`：新分支行 + 可选快照行 + sessions
      active_branch/head/version 同一事务 + 乐观锁；失败整事务回滚
- [x] 端到端：回溯→重新选择→新分支状态一致且历史可审计（血缘链可重建完整历史）
- 附带修复：#4 DB 集成测试基建 —— sessions.script_id/material_id 去库级 FK
      （与 active_branch_id 同原则，消除循环依赖）；pytest-asyncio loop scope 统一
      session 级（修 asyncpg「another operation in progress」）；alembic 迁移测试
      在线迁移改独立线程执行（修 asyncio.run 嵌套）；_accept_command 用
      scalar_one_or_none + 显式 flush（修自动 flush 顺序问题）
- 测试：`tests/test_branch_replay.py`（7 例）+ `tests/test_branch_persistence.py`（2 例，
      无 PG 自动 skip）

### [#10] 安全开放网络 RAG ✅ 已完成（2026-09-05）

- [x] SearchProvider/PageFetcher/DocumentExtractor 契约 + 首个实现
      —— `app/rag/providers.py`（Protocol + NullSearchProvider）；`SafePageFetcher`；
      `HtmlDocumentExtractor`
- [x] 仅 http/https；DNS 解析后拒绝 loopback/private/link-local/metadata；每次重定向复检
      —— `app/rag/network.py`（封禁网段白名单 + `validate_target`；fetch 每跳前复检）
- [x] 连接/读取超时、响应体大小、并发、content-type 白名单生效
      —— SafePageFetcher（timeout/5MB/信号量4/text-html·xhtml·plain）
- [x] HTML 清洗（去 script/style/注释/隐藏内容）；网页文本标记不可信，指令隔离
      —— HtmlDocumentExtractor + `mark_untrusted`（显式隔离标签）
- [x] 来源记录：URL/标题/抓取时间/内容 hash/引用片段 → WebEvidence
- [x] SSRF/重定向/超时/恶意内容测试；失败降级为纯原文（RagService 空证据集）
- [x] 搜索 provider 选型与降级策略 ADR：`docs/adr/0001-rag-provider-selection.md`
- 新增错误码：SEARCH_UNAVAILABLE(8001)/SEARCH_BLOCKED_TARGET(8002)/SEARCH_TIMEOUT(8003)
      + diagnostics 稳定码映射 + 安全文案；httpx 提升为主依赖
- 测试：`tests/test_rag.py`（14 例，全程 MockTransport 无真实网络）

### [#11] Schema-first Stage1 生成与验证 ✅ 已完成（2026-09-05）

- [x] 严格版本化 schema 生成角色设定/场景/beats/教学重点/可扮演角色
      —— `app/generation/stage1.py`：JSON → `ScriptPackage.model_validate_json`
      （contracts.script 冻结 schema，extra=forbid）
- [x] Stage2 关键 beat 均带原文 EvidenceRef；人物/事件顺序符合原文
      —— `synthesize_script_package` + validators（characters/event_order 校验）
- [x] 结构/证据覆盖/人物一致性/事件顺序/教学适配五类校验，失败重试 ≤2
      —— `app/generation/validators.py`（validate_all）；generate 失败带反馈重试 ≤2
- [x] 纯原文不足（无人物或无关键事件）明确报 CONTENT_INSUFFICIENT_SOURCE，不产出半合法剧本
- [x] 记录 model/prompt version/schema version/latency/token/retry → GenerationTelemetry
- [x] 多篇叙事课文 fixture 产出合法 ScriptPackage；非叙事文本返回正确错误
- 新增错误码：CNT_INSUFFICIENT_SOURCE(6002)/CNT_GENERATION_FAILED(6003)
      + diagnostics 映射 + 安全文案
- 测试：`tests/test_stage1.py`（14 例：多 fixture 合法产出/结构化输出+telemetry/
      重试≤2/不足报错/五类校验各自拒收/非叙事拒绝）
- 真实 LLM 冒烟验证（2026-09-05，DeepSeek）：prompt stage1.v1 重设计——严格字段类型
      契约（scene_id/beat_id 必须整数、evidence_refs 必须对象数组）+ 关键事件证据
      JSON 可原样复制 + 解析侧剥 markdown 围栏/夹杂文本；首次尝试（retries=0）产出
      合法 ScriptPackage、五类校验全过。实测延迟 ~103s → llm_timeout_seconds 默认
      上调 150s，并经 ModelServiceFactory 透传（此前 settings 超时/并发被忽略）

## 第四波

### [#5] Fake-backed 后端竖切 ✅ 已完成（2026-09-05）

架构接缝三件套：
- `core/script_adapter.py`（ScriptPackage→引擎 Script）
- `db/event_store.py`（int↔UUID 分支确定性映射 `branch_uuid`/`event_uuid`、
      `write_pending` 事务外置、分支感知 `restore_active_branch`）
- `session/projection.py`（StepResult/export_state→契约 RuntimeUpdate/RuntimeState/WS 消息）
- `session/application.py` SessionApplication：create/import（真实 ingestion）/
      generate（fake 确定性合成，可注入 LLM）/submit_command/get_status/session_init/replay_after
- REST 5 端点（会话/状态/材料/生成/命令）+ WJError→envelope 错误映射；
      WS `/ws/{session_id}`（session_init + submit_command + confirm/resync）

验收勾选：
- [x] POST 创建会话写入真实 sessions 表；GET 会话状态可查
- [x] 导入材料走真实 ingestion 校验，生成用 fake（确定性合成；真实 LLM 可注入，
      Stage1 真实链路已在 #11 冒烟验证）
- [x] 生成进度可查询（fake pipeline：运行中/成功/失败）
- [x] 选角后 PlayerCommand 经 WS 提交，返回 RuntimeUpdate 投影
- [x] 消息仅事务提交后发布；command_id 幂等（commands 表闸 + runtime 内存闸）
- [x] 断线重连：session_init 重建阶段/历史/交互点；resync 按 last_confirmed 补发
      （WS outbox 优先，跨连接走 `replay_after` 从 DB 活动分支重建）
- [x] 脚本（curl/WS 客户端）完整演示：`scripts/demo_flow.py` + `make demo`
      （创建→导入→生成→WS 选角→推进→回溯分支→重连恢复，实测通过）
- [x] 后端集成测试覆盖（真实 PG + fake adapters）：
      test_session_application 6 例 + test_api_sessions 5 例 + test_projection 4 例

附带修复（本轮）：
- 两个隐蔽 falsy 陷阱：GameRuntime `event_store or EventStore()` 因空存储 __len__=0
  为 falsy 而静默丢弃传入的 PersistentEventStore（build_runtime_with_db 落库挂接
  一直失效）；`_next_sequence` 的 `0 or -1` 在 max(sequence)=0 时重复发号
- GameRuntime 命令事件缓冲（`_command_events`）：此前 system/stage_transition/
  player_action 类事件不进 sink，命令结果与 WS 实时消息漏发这两类事件
- WS seq = 活动分支路径序号（回溯后可见正确回卷，audit 友好）
- 注：REST 粘贴导入已通；multipart 文件上传（.txt/.md 直传）留待前端 #6 联调时补

## 第五波

### [#12] 真实核心集成（Stage1→2→3 + 恢复 + 回溯端到端）✅ 已完成（2026-09-05）

- [x] SessionApplication 接入真实组件：routes 组装真实 script_llm（配置 key 时
      agent/script 共用 provider）+ RagService（研究阶段接入生成管线，进度如实
      反映 succeeded/degraded）；UnitOfWork 即既有命令单事务受理
- [x] 真实课文端到端：`scripts/e2e_real_flow.py`（真实 LLM 实测通过：真实
      Stage1 产出「买药·离别」→ 选角 → Stage2 推进至结局确认 → Stage3
      自由输入/选项 → 回溯 → 退出 → 终局后 SESSION_ENDED envelope）
- [x] 三交互模式真实生效：Stage2=options(A)、Stage3=options_with_fallback(C)、
      free_input(B)，test_full_flow + e2e 双断言
- [x] Stage3 目标导向自然收敛：rounds-limit 自然终止 + confirm_ending/exit_game
      显式终局（stage3_goals 契约字段保留，目标推荐随后续内容质量迭代）
- [x] 消息仅事务提交后发布；WS 重连补发；进程重启从 PG 恢复（#5 集成测试覆盖，
      e2e 重连重建复验）
- [x] 回溯真实链路可用且保留历史（新分支断言 + 旧分支事件仍在库）
- [x] 浏览器 E2E（Playwright/chromium，`npm run test:e2e`）：创建→导入→生成→
      选角→选项推进→回溯→刷新恢复 1.7s 全过；真实 LLM 模式亦实测通过
- [x] 所有对外错误符合 envelope；error_id 可对账（SESSION_ENDED /
      CONTENT_UNSUPPORTED_GENRE / 幂等重发对账测试断言）
- 附带修复（E2E 暴露）：
  - **CORS 中间件缺失**：浏览器跨域调用全部失败（此前无浏览器级验证）
  - 终局路径残留 active_interaction → 投影出过期交互点而非「已结束」
  - 终局双消息同 seq（进入阶段：ended + 已结束）被前端 seq:type 去重丢弃
    → 去重键加文本
  - SESS_ENDED(1002) 已定义从未抛出 → SessionApplication 增终局闸
- 注：analyzer 把「路上小心。」误识为人物「住我的手」（引号归属 bug，
  #14 Gold Set 评分时一并处理）

### [#13] 生产化加固（故障注入与可恢复性）✅ 已完成（2026-09-14）

- [x] LLM 超时/非法结构化输出 → 明确 retryable/terminal，无部分状态
      —— `llm_service` 统一 wrap LLM_CALL_FAILED；Stage1 非法输出重试 ≤2 后
      CNT_GENERATION_FAILED；失败不落 script 行（`test_resilience` 断言）
- [x] 搜索失败/恶意网页/抓取超时 → 降级或明确错误
      —— `RagService.research` 任意失败降级为空证据（纯原文）；新增测试
- [x] DB 事务失败 → 无部分状态、无成功消息发布
      —— `_persist_command`/`_commit_system_events` 单事务 + DB 错误 wrap 为
      PER_WRITE_FAILED；受理失败丢弃内存运行时，下次从 DB 权威重建
- [x] WS 中断与命令重发 → 幂等、补发、无重复事件（commands 表 + 运行时双闸）
- [x] 进程重启 → 会话恢复一致（restore_active_branch + 快照重放）
- [x] snapshot 损坏 / schema 版本不兼容 → 可重建，不崩溃
      —— `_restore_runtime` 校验 snapshot schema_version/payload，异常时忽略
      快照从完整事件流重建；剧本数据不兼容返回 PERSISTENCE_INCOMPATIBLE_SCHEMA
- [x] 上述场景均有自动化测试 —— `tests/test_resilience.py`（8 例，真实 PG）

### [#14] 课文内容质量 Gold Set 与人工评分门禁

- [ ] 5–10 篇不同叙事类型课文 gold set，含拒收边界样本
- [ ] 评测维度：人物识别/关键事件覆盖/事件顺序/原文证据/人设一致性/Stage2 偏离率/Stage3 连贯性与收敛
- [ ] 生成与评分脚本可复跑；人工评分表落盘
- [ ] 结果评审确定 MVP 质量基线；未达标缺陷回流对应 ticket

## 基础设施层（横切，配合对应 issue 落地）

### Infra (docker-compose / 部署) ✅ 已完成（2026-09-14）
- [x] backend Dockerfile（uv 依赖锁 + 非 root + `/health/live` HEALTHCHECK + 入口迁移脚本）
- [x] frontend Dockerfile（Next.js standalone 多阶段构建）
- [x] docker-compose：db + backend + frontend + nginx（同源入口）四服务 + 卷
      （nginx 反代 `/api`、`/ws`，浏览器同源，避免跨域与硬编码端口）
- [x] backend healthcheck（`/health/live` 容器级 + `/health/ready` 依赖级）
- [x] Makefile 补 build-backend/build-frontend/up/down/logs/e2e

### CI ✅ 已完成（2026-09-14）
- [x] `.github/workflows/ci.yml`：backend lint+pytest（含 PG，不 skip）+ 迁移 + 契约一致性测试
- [x] frontend lint + tsc + next build
- [x] 浏览器 E2E（Playwright）对真实 REST/WS + PG 跑核心流程
- [x] 故障注入测试纳入 pytest 门禁（test_resilience.py）；契约变更 reviewer 由流程文档约束

## 关键风险与取舍

- **design_07（保留长驻 run + asyncio.Task 糊）已被 issue 体系取代**：以 #7 command/step 重构为准，生产路径禁用 长驻 run()。design_07 归为过期文档。
- **#4 DB schema 变更**（commands/event_branches + events 加字段）触及 game_engine 落库路径，建议与 #7 同批处理避免二次迁移。
- **前后端契约共享**：Next.js 与 Python 无法共享类型，务实做法是 `contracts/fixtures/*.json` 单源 + 两端各自语言类型 + CI 断言一致（#2 验收已含此测试）。
- **#6 mock server**：需先有 #2 fixtures，用其驱动前端开发（可复用 fake adapters 的真后端或独立 mock）。

## 规模估算（相对）

| Issue | 相对规模 | 关键交付 |
|---|---|---|
| #2 | 中 | contracts 包 + fixtures + 一致性测试 |
| #3 | 中 | errx 扩展 + logging + health + metrics |
| #4 | 中 | 迁移 + 2 新表 + events/sessions 加字段 + 事务 |
| #7 | 大 | GameRuntime 重构（最大改造） |
| #6 | 大 | 前端完整产品线 + mock + E2E |
| #9/#11 | 大 | 内容管线深模块 |
| #10 | 中 | RAG 安全适配器 |
| #8 | 中 | 回放/幂等/回溯语义 |
| #5 | 中 | SessionApplication 竖切 |
| #12 | 大 | 真实集成端到端 |
| #13 | 中 | 故障注入矩阵 |
| #14 | 中 | Gold Set 评分流程 |