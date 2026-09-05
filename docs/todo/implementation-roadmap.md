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

### [#6] 前端 mock 全流程

- [ ] 导入页：粘贴 + .txt/.md 上传、校验错误展示
- [ ] 生成进度页：体裁判断/网络研究/生成/验证阶段状态与失败定位
- [ ] 选角页：角色列表与简介、可扮演标记、开始游戏
- [ ] 游戏页：叙事/角色发言/系统消息/交互点渲染；options/free_input/options_with_fallback 三输入
- [ ] command 提交 pending 态：幂等 + 按 command_id 对账
- [ ] 刷新恢复 + WS 指数退避重连；回溯确认与活动时间线
- [ ] 错误按产品阶段呈现（input/content/search/llm/session/game）
- [ ] 对 mock server 的浏览器测试覆盖核心流程

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

### [#3] 建立统一诊断基础设施

- [ ] 结构化日志（部署 JSON / 开发可读）；标准字段 id/duration_ms/error_code/retry_count

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

### [#9] 课文导入 / 体裁判断 / 原文证据模型

- [ ] 粘贴 + .txt/.md 上传校验（编码/空内容/大小/扩展名）；规范化 + 内容 hash
- [ ] 叙事体裁判断：小说/叙事文/戏剧/人物故事通过；说明文/议论文/纯写景/诗歌返回 CONTENT_UNSUPPORTED_GENRE
- [ ] 原文分析：人物/关系/场景/关键事件，关联原文字符区间/段落
- [ ] EvidenceRef 区分原文证据与网络补充
- [ ] 同输入下 deterministic 一致

## 第三波

### [#8] 运行时回放 / 命令幂等 / 分支回溯

- [ ] snapshot + active-branch 事件重放后与原 RuntimeState 一致（属性级断言）
- [ ] 非法 stage/命令返回稳定 GAME_* 错误；allowed_commands 生效
- [ ] 回溯：旧事件保留、新 active branch 从目标节点创建、head 更新
- [ ] 回溯后后续命令只追加到新活动分支
- [ ] 快照与 branch/head 更新原子提交
- [ ] 端到端：回溯→重新选择→新分支状态一致且历史可审计

### [#10] 安全开放网络 RAG

- [ ] SearchProvider/PageFetcher/DocumentExtractor 契约 + 首个实现
- [ ] 仅 http/https；DNS 拒绝 loopback/private/link-local/metadata；每次重定向复检
- [ ] 连接/读取超时、响应大小、并发、content-type 白名单
- [ ] HTML 清洗；网页文本标记不可信，指令隔离
- [ ] 来源记录：URL/标题/抓取时间/内容 hash/引用片段
- [ ] SSRF/重定向/超时/恶意内容测试；失败降级为纯原文
- [ ] 搜索 provider 选型 + 降级策略 ADR

### [#11] Schema-first Stage1 生成与验证

- [ ] 严格版本化 schema 生成角色设定/场景/beats/教学重点/可扮演角色
- [ ] Stage2 关键 beat 均带原文 EvidenceRef；人物/事件顺序符合原文
- [ ] 结构/证据覆盖/人物一致性/事件顺序/教学适配五类校验，失败重试 ≤2
- [ ] 纯原文不足时明确报错或降级说明，不产出半合法剧本
- [ ] 记录 model/prompt version/schema version/latency/token/retry
- [ ] 多篇叙事课文 fixture 产出合法 ScriptPackage；非叙事文本返回正确错误

## 第四波

### [#5] Fake-backed 后端竖切

- [ ] POST 创建会话写入真实 sessions 表；GET 会话状态可查
- [ ] 导入材料走真实 ingestion 校验（粘贴/TXT/MD），生成用 fake
- [ ] 生成进度可查询（fake pipeline：运行中/成功/失败）
- [ ] 选角后 PlayerCommand 经 WS 提交（fake runtime），返回 RuntimeUpdate 投影
- [ ] 消息仅事务提交后发布；command_id 幂等
- [ ] 断线重连：session_init 重建阶段/历史/交互点；按 last confirmed 位置补发
- [ ] 脚本（curl/WS 客户端）完整演示：创建→导入→生成→选角→submit→interaction→刷新恢复
- [ ] 后端集成测试覆盖上述路径（真实 PG + fake adapters）

## 第五波

### [#12] 真实核心集成（Stage1→2→3 + 恢复 + 回溯端到端）

- [ ] SessionApplication 接入真实 ContentPipeline/GameRuntime/RAG/UnitOfWork
- [ ] 真实课文端到端：导入→生成→选角→Stage2 至结局确认→Stage3→退出
- [ ] 三交互模式真实生效；Stage3 目标导向自然收敛
- [ ] 消息仅事务提交后发布；WS 重连补发；进程重启从 PG 恢复
- [ ] 回溯在真实链路可用且保留历史
- [ ] 浏览器 E2E 覆盖完整核心流程
- [ ] 所有对外错误符合 envelope；错误可经 error_id 定位

### [#13] 生产化加固（故障注入与可恢复性）

- [ ] LLM 超时/非法结构化输出 → 明确 retryable/terminal，无部分状态
- [ ] 搜索失败/恶意网页/抓取超时 → 降级或明确错误
- [ ] DB 事务失败 → 无部分状态、无成功消息发布
- [ ] WS 中断与命令重发 → 幂等、补发、无重复事件
- [ ] 进程重启 → 会话恢复一致
- [ ] snapshot 损坏 / schema 版本不兼容 → 明确错误或可重建，不崩溃
- [ ] 上述场景均有自动化测试

### [#14] 课文内容质量 Gold Set 与人工评分门禁

- [ ] 5–10 篇不同叙事类型课文 gold set，含拒收边界样本
- [ ] 评测维度：人物识别/关键事件覆盖/事件顺序/原文证据/人设一致性/Stage2 偏离率/Stage3 连贯性与收敛
- [ ] 生成与评分脚本可复跑；人工评分表落盘
- [ ] 结果评审确定 MVP 质量基线；未达标缺陷回流对应 ticket

## 基础设施层（横切，配合对应 issue 落地）

### Infra (docker-compose / 部署)
- [ ] backend Dockerfile（uv 依赖锁 + uvicorn）
- [ ] frontend Dockerfile（Next.js 多阶段构建）
- [ ] docker-compose：db + backend + frontend 三服务 + 共享网络 + 卷（#3 提供 healthcheck 端点支撑）
- [ ] backend healthcheck（/health/live + /health/ready）
- [ ] Makefile 补 build-backend/build-frontend/up/E2E

### CI（当前完全缺失）
- [ ] `.github/workflows/ci.yml`：backend lint+pytest（含 PG，不 skip）+ 契约一致性测试
- [ ] frontend lint + tsc + next build
- [ ] 浏览器 E2E（Playwright）对真实 REST/WS + PG 跑核心流程
- [ ] 故障注入门禁；契约变更需 reviewer

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