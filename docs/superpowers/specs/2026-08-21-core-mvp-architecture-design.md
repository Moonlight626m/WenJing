# 文境核心 MVP 架构与并行开发设计

**状态：** 待用户书面复核
**日期：** 2026-08-21
**目标分支：** `dev`

## 1. 目标

文境的目标是交付一个可投入真实试用的语文课文情景演绎产品，而不是固定 fixture、演示脚本或技术玩具。

核心 MVP 必须完成以下闭环：

1. 用户粘贴课文或上传 `.txt` / `.md` 文件。
2. 系统判断文本是否属于支持的叙事类课文。
3. 系统结合课文原文和开放网络资料生成带证据引用的可玩剧本。
4. 用户选择一个可扮演角色。
5. 用户完成 Stage 2 原文关键情节还原。
6. 用户确认后进入 Stage 3，在原有人物和世界设定内续写。
7. 系统支持选项、自由输入、混合三种交互模式。
8. 会话刷新、断线或进程重启后可以恢复。
9. 用户可以回溯并从历史节点产生新的活动时间线。
10. 核心链路失败时有明确错误反馈，并可通过日志和关联 ID 快速定位。

首版不包含账号、多租户、支付、社区、多人联机、TTS/ASR、图片生成、多结局可视化编辑器和通用课文体裁支持。

## 2. 已冻结的产品边界

### 2.1 用户和部署

- 单用户、单课文、单会话体验。
- 固定扮演一个主角，其他角色由 Agent 驱动。
- 首个部署基线为单机 Docker Compose：Next.js、FastAPI、PostgreSQL。
- LLM 和开放网络检索使用外部 provider。
- 不引入 Redis、Kafka、Kubernetes 或微服务。
- 保持模块化单体；只有出现真实独立扩缩容或部署需求后才评估拆服务。

### 2.2 输入和体裁

- 支持网页文本粘贴。
- 支持 `.txt` / `.md` 文件上传。
- 只承诺小说、叙事文、戏剧、人物故事等叙事类课文。
- 说明文、议论文、纯写景文本和大部分诗歌不在核心 MVP 支持范围。
- 系统必须先执行适配性判断；不适配时返回明确错误，禁止强行生成劣质剧本。

### 2.3 内容来源

- Stage 2 的人物、关系、关键事件和事件顺序必须由课文原文证据支持。
- 开放网络资料用于补充时代背景、作者背景、教学解读和文化信息。
- 网络资料不能覆盖或改写原文中的 Stage 2 关键事实。
- 每条外部资料必须保存 URL、标题、抓取时间、内容 hash 和实际引用片段。
- 搜索或抓取失败时降级为仅使用课文原文，不使整个产品不可用。

## 3. 架构原则

1. **领域事件是游戏事实。** WebSocket 消息只是可重建的展示投影。
2. **命令是唯一输入入口。** 所有玩家操作通过带唯一 `command_id` 的 `PlayerCommand` 进入游戏运行时。
3. **运行状态显式化。** 不用长驻协程的隐式栈帧承担会话状态。
4. **核心与 adapter 分离。** Gameplay Core 不依赖 FastAPI、SQLAlchemy、WebSocket 或网络检索。
5. **契约先行。** 四条工作流在共享类型和协议冻结后并行开发。
6. **事务提交后发布。** 领域事件和状态成功提交后，Session Platform 才向客户端发送对应消息。
7. **事件历史不物理删除。** 回溯保留旧历史并切换活动 head。
8. **严格结构化 LLM 输出。** 不合法输出不能进入领域状态。
9. **诊断设施属于 MVP 地基。** 日志、错误、关联 ID、健康检查和基础指标从第一轮实现开始统一。
10. **不预造假 seam。** 当前只实现有真实调用方的 adapter；Redis、对象存储、通知和认证等到出现真实需求再补。

## 4. 总体模块

```text
┌──────────────── Frontend Product ────────────────┐
│ 导入 / 生成进度 / 角色选择 / 游戏 / 回溯 / 恢复  │
└──────────────────────┬───────────────────────────┘
                       │ REST + WebSocket DTO
┌──────────────────────▼───────────────────────────┐
│ Session Platform                                 │
│ 会话生命周期 / 命令串行化 / 幂等 / 协议映射       │
├───────────────┬───────────────────┬──────────────┤
│ Content       │ Gameplay Core     │ Persistence  │
│ Pipeline      │                   │ Adapters     │
│ 导入/RAG/生成 │ command→events    │ PG/repos/UoW │
└───────┬───────┴──────────┬────────┴───────┬──────┘
        │                  │                │
   Search/Fetch       LLM Gateway      PostgreSQL
     adapters           adapter
```

部署仍是一个后端进程。模块边界用于控制依赖、测试面和多人所有权，不代表微服务边界。

## 5. Shared Contracts

建议位置：

```text
backend/app/contracts/
  material.py
  script.py
  commands.py
  events.py
  runtime.py
  errors.py
  protocol.py
```

核心类型：

- `MaterialInput`
- `Material`
- `EvidenceRef`
- `ScriptPackage`
- `PlayerCommand`
- `DomainEvent`
- `RuntimeState`
- `GameSnapshot`
- `RuntimeUpdate`
- `ErrorEnvelope`

共同不变量：

- 原文证据和网络补充使用不同来源类型。
- `ScriptPackage` 中每个 Stage 2 关键 beat 必须带至少一个原文 `EvidenceRef`。
- 每个 `PlayerCommand` 包含唯一 `command_id`、`session_id`、命令类型和 payload。
- 每个 `DomainEvent` 包含 `event_id`、`session_id`、`branch_id`、`sequence`、`causation_id`、`correlation_id`、`schema_version` 和 payload。
- `RuntimeState` 不包含 WebSocket、FastAPI、SQLAlchemy session 或具体 LLM client。
- 领域模型与 REST/WebSocket DTO 不共用同一个类；通过显式 mapper 转换。
- Shared Contracts、数据库迁移和外部协议的 breaking change 需要至少两名开发者 review。

## 6. Content Pipeline

### 6.1 外部接口

```python
class ContentPipeline:
    async def create_script(
        self,
        material: Material,
        options: GenerationOptions,
    ) -> ScriptPackage: ...
```

### 6.2 内部模块

#### Ingestion

- 接收粘贴文本或 `.txt` / `.md`。
- 校验编码、文件大小、空内容和扩展名。
- 规范化换行和 Unicode，计算内容 hash。
- 不承担剧情推理。

#### Genre Classifier

- 判断是否为支持的叙事类文本。
- 输出类型化结果和判断依据。
- 不适配时返回稳定的 `CONTENT_UNSUPPORTED_GENRE`。

#### Original-text Analyzer

- 提取人物、关系、场景和关键事件。
- 每项结论关联原文字符区间或段落标识。
- 为 Stage 2 的事实约束提供唯一权威来源。

#### Open-web Research

内部 seam：

```python
class SearchProvider: ...
class PageFetcher: ...
class DocumentExtractor: ...
```

安全约束：

- 仅允许 `http` / `https`。
- DNS 解析后拒绝 loopback、private、link-local 和云 metadata 地址。
- 每次重定向重新校验目标。
- 限制连接超时、读取超时、响应体大小和并发。
- 使用 content-type 白名单。
- 清除脚本、样式、隐藏内容和不可见控制字符。
- 网页文本始终作为不可信数据，不与系统指令拼接在同一信任区。
- 资料中的命令、角色指令和工具调用要求一律忽略。
- 抓取失败、解析失败或检索超时均可降级。

具体搜索 provider 是 adapter 选择，不改变 `SearchProvider` 契约；首个实现必须通过独立 ADR 记录 provider、成本、配额、隐私和降级策略。

#### Script Generator

- 组合原文分析与外部背景证据。
- 生成角色设定、场景、beats、教学重点和可扮演角色。
- Stage 2 关键事实只接受原文证据。
- Stage 3 可以使用背景资料扩展，但不能破坏人物和世界设定。

#### Script Validator

- Pydantic 结构校验。
- 原文证据覆盖校验。
- 人物一致性校验。
- 关键事件顺序校验。
- 教学适配性校验。
- 最多重试 2 次；重试失败返回类型化错误，不输出半合法剧本。

### 6.3 独立验收

使用 fake Search、Fetcher 和 LLM：

- 叙事课文可以产出合法 `ScriptPackage`。
- 非叙事文本稳定拒绝。
- 每个 Stage 2 关键 beat 有原文证据。
- 搜索失败时仅用原文完成或给出可解释失败。
- 相同输入和 deterministic fake 得到稳定输出。

## 7. Gameplay Core

### 7.1 外部接口

现有 `GameEngine.run(player_decision)` 不再作为产品主链路。核心 MVP 使用可恢复的 command/step 模型：

```python
class GameRuntime:
    def start(
        self,
        script: ScriptPackage,
        player_role: str,
    ) -> RuntimeUpdate: ...

    async def submit(
        self,
        state: RuntimeState,
        command: PlayerCommand,
    ) -> RuntimeUpdate: ...

    def restore(
        self,
        snapshot: GameSnapshot,
        events: Sequence[DomainEvent],
    ) -> RuntimeState: ...

    def rollback(
        self,
        state: RuntimeState,
        target_event_id: int,
    ) -> RuntimeUpdate: ...
```

`RuntimeUpdate` 至少包含：

```python
@dataclass(frozen=True)
class RuntimeUpdate:
    state: RuntimeState
    events: tuple[DomainEvent, ...]
    interaction: InteractionPoint | None
    allowed_commands: frozenset[CommandType]
    status: RuntimeStatus
```

### 7.2 内部职责

- Stage 状态机。
- beat 进度和 8 步 phase cycle。
- NPC 并行提议与反应。
- 验证、重试和降级。
- options / free_input / options_with_fallback。
- Stage 2 原文关键事件约束。
- Stage 2 结局确认。
- Stage 3 小目标、完成判断和自然收敛。
- 角色记忆和剧情上下文。
- 回溯、分支和事件重放。

### 7.3 必要重构

- `ScreenwriterAgent.beat_index` 移入 `RuntimeState`。
- `stage3_round_taken` 移入 `RuntimeState`。
- 角色记忆成为版本化、可序列化状态。
- 当前长驻 `run()` 可暂时保留为测试便利 adapter，但不能被 REST/WS 主链路调用。
- Agent 只依赖注入的 `LLMGateway`。
- 重复 `command_id` 不产生重复事件。
- 每次 submit 推进到下一个稳定中断点并返回，不跨请求保留隐式等待栈。

### 7.4 独立验收

- 固定 `ScriptPackage` 和 deterministic fake LLM 可以完成 Stage 2/3。
- snapshot + replay 后状态与原状态一致。
- 重复 command 幂等。
- 非法 stage/command 返回稳定错误。
- 回溯后旧事件保留，新活动分支从目标节点继续。

## 8. Session Platform

### 8.1 外部接口

```python
class SessionApplication:
    async def create_session(self) -> SessionView: ...
    async def import_material(
        self,
        session_id: UUID,
        source: MaterialInput,
    ) -> MaterialView: ...
    async def generate_script(self, session_id: UUID) -> GenerationView: ...
    async def select_role(
        self,
        session_id: UUID,
        role: str,
    ) -> RuntimeView: ...
    async def submit(
        self,
        session_id: UUID,
        command: PlayerCommand,
    ) -> RuntimeUpdate: ...
    async def recover(self, session_id: UUID) -> RuntimeView: ...
```

### 8.2 职责

- session 生命周期和状态转换。
- 每 session 命令串行化。
- `command_id` 幂等。
- 调用 Content Pipeline 和 Gameplay Core。
- 在同一事务内提交 command 状态、领域事件、active head、snapshot 和 session version。
- commit 成功后将领域事件投影成 OutboundMessage。
- REST/WS DTO mapper。
- WebSocket 重连后的 `session_init` 和 missed-message 补发。
- 配置、LLM Gateway、Search adapter、repository 和 runtime 的组合根。
- 生成任务的状态、失败和恢复。
- 日志、错误、health、readiness 和 metrics。

### 8.3 禁止职责

- 不实现剧情规则。
- 不解析具体 LLM 结构化内容。
- route 不直接访问 ORM。
- WebSocket 不直接持有或调用旧 `GameEngine.run()`。
- 不为当前没有调用方的 Redis、对象存储、通知和认证预造接口。

## 9. Persistence Adapters

建议接口：

```python
class SessionRepository: ...
class MaterialRepository: ...
class ScriptRepository: ...
class CommandRepository: ...
class EventRepository: ...
class BranchRepository: ...
class SnapshotRepository: ...

class UnitOfWork:
    sessions: SessionRepository
    materials: MaterialRepository
    scripts: ScriptRepository
    commands: CommandRepository
    events: EventRepository
    branches: BranchRepository
    snapshots: SnapshotRepository

    async def commit(self) -> None: ...
    async def rollback(self) -> None: ...
```

### 9.1 数据概念

```text
commands
  command_id
  session_id
  payload
  status
  result_event_id
  created_at

event_branches
  branch_id
  session_id
  parent_branch_id
  fork_event_id
  head_event_id
  status

events
  event_id
  session_id
  branch_id
  sequence
  event_type
  schema_version
  causation_id
  correlation_id
  payload

snapshots
  snapshot_id
  session_id
  branch_id
  event_id
  runtime_state
  schema_version
```

### 9.2 约束

- 正式环境只使用 Alembic migration，不用 `create_all()` 替代迁移。
- 事件 append-only。
- 回溯保留旧分支事件，更新 session 的 active branch/head。
- MVP UI 不要求展示旧分支，但数据库保留审计历史。
- snapshot 是性能优化，不是事实源。
- JSONB 事件和 snapshot 带 schema version。
- command 执行使用 session version 或数据库锁防止并发提交。
- 事务提交失败不得向 WebSocket 发布成功消息。

## 10. Frontend Product

前端按用户流程组织：

1. **Material Import**：文本粘贴、TXT/MD 上传、输入校验。
2. **Generation Progress**：适配性判断、网络研究、剧本生成、验证和失败阶段展示。
3. **Role Selection**：角色简介和可扮演角色选择。
4. **Game Experience**：叙事、角色发言、三种输入模式、等待和降级状态。
5. **Recovery and Rollback**：刷新恢复、WS 重连、回溯确认和恢复失败反馈。

前端约束：

- 不复制游戏规则。
- 使用冻结的 REST/WS DTO。
- command 提交后禁用重复操作，直到收到相同 `command_id` 的结果或错误。
- WebSocket 重连必须携带 session 和最后确认消息位置。
- 可以通过 mock server 和 contract fixtures 独立开发。

## 11. LLM 合同

采用 Schema-first strict：

- 所有结构化产物使用版本化 Pydantic schema。
- 优先使用 provider 原生 structured output。
- 解析或验证失败最多重试 2 次。
- 重试失败返回类型化错误或执行明确的降级，不生成半合法对象。
- fallback model/provider 必须显式配置并写入日志；禁止静默切换。
- 每次调用记录 provider、model、prompt version、schema version、latency、token、retry 和结果状态。
- API key、完整 prompt、完整课文和玩家自由输入默认不进入日志。

具体 LLM provider 由环境配置和 adapter 选择；provider 变化不得改变 `LLMGateway` 和领域合同。

## 12. 开发诊断基础设施

### 12.1 结构化日志

部署模式输出 JSON，开发模式可提供人类可读 formatter。统一字段：

```text
timestamp
level
logger
event
request_id
session_id
command_id
generation_id
llm_call_id
correlation_id
duration_ms
error_code
retry_count
```

- 使用 `contextvars` 传播关联字段。
- 搜索、抓取、LLM、command、DB transaction 和 WS 生命周期均记录开始、完成、失败。
- 默认禁止记录 API key、完整课文、完整 prompt 和完整玩家输入。
- 调试内容必须显式开启、截断并脱敏。

### 12.2 统一错误

沿用现有 `errx`，对外统一：

```json
{
  "error_id": "uuid",
  "code": "CONTENT_UNSUPPORTED_GENRE",
  "message": "当前仅支持叙事类课文",
  "retryable": false,
  "details": {}
}
```

错误分类：

- `INPUT_*`
- `CONTENT_*`
- `SEARCH_*`
- `LLM_*`
- `GAME_*`
- `SESSION_*`
- `PERSISTENCE_*`
- `PROTOCOL_*`
- `INTERNAL_*`

cause 和 stack 只写服务端日志，不返回客户端。

### 12.3 健康和指标

- `/health/live`：进程存活。
- `/health/ready`：必要配置和 PostgreSQL 可用。
- 外部搜索和 LLM 不作为 readiness 硬依赖。
- `/metrics`：请求数、错误数、生成成功率、LLM 时延/token、搜索时延、WS 连接数、command 时延、DB transaction 失败数。
- Docker Compose 为 backend、frontend 和 PostgreSQL 配置 healthcheck。
- 核心 MVP 不要求部署 Grafana、ELK 或 OpenTelemetry Collector，但日志和指标格式应可后续接入。

### 12.4 诊断验收

- 任意错误响应可用 `error_id` 定位服务端 stack 和上下文。
- 任意 session 可串联 command、event、LLM、搜索和 DB transaction。
- 能区分 WebSocket 重发与新 command。
- 未捕获异常统一返回 `INTERNAL_ERROR`。
- LLM 和搜索记录时延、重试和降级，但不泄漏凭证或全文。

## 13. 依赖图和关键路径

```text
Shared Contracts
├── Content Pipeline
├── Gameplay Core
├── Session Platform
└── Frontend protocol types

Content Pipeline ───────┐
Gameplay Core ──────────┼──> Session Platform ──> REST / WebSocket
Persistence Adapters ───┘
                                      ↑
Frontend Product ─────────────────────┘
```

禁止反向依赖：

- Gameplay Core 不依赖 Session Platform。
- Content Pipeline 不依赖 Gameplay Core。
- Core 不依赖 FastAPI/SQLAlchemy。
- Frontend 不实现游戏状态判断。
- Persistence 不调用 LLM。
- RAG 不直接写数据库或发送 WebSocket。

关键路径：

```text
契约冻结
→ step/command GameRuntime
→ 真实 Stage1 ScriptPackage
→ SessionApplication 集成
→ REST/WS 命令与消息闭环
→ 前端完整流程
→ 恢复、回溯与故障验证
```

## 14. 3–4 人并行分工

### Developer A：Gameplay Core Owner

负责 Gameplay Core、command/event/runtime 合同、Stage2/3、回放和 core 测试。

独立验收：固定剧本经过 command 序列完成游戏，snapshot/replay 一致，重复 command 幂等。

### Developer B：Content Pipeline Owner

负责 ingestion、体裁判断、原文证据、开放网络 RAG、Stage1、剧本验证和内容质量 fixtures。

独立验收：多篇叙事课文产生带原文证据的合法剧本；非叙事拒绝；搜索失败可降级。

### Developer C：Session Platform + Persistence Owner

负责 SessionApplication、REST/WS、事务、Alembic、repository/UoW、恢复、LLM 配置、Docker Compose 和诊断设施。

独立验收：使用 fake ContentPipeline/GameRuntime 完成创建、导入、生成、选角、submit、落库、重连和重启恢复。

### Developer D：Frontend Product Owner

负责导入、生成进度、角色选择、游戏 UI、三种输入、错误反馈、重连和回溯体验。

独立验收：使用 mock server 完成完整核心用户流程，刷新/断线可恢复，重复提交受控。

三人团队时，优先保留 A/B/C 三条后端真实闭环；前端在 contract mock 基础上作为下一并行批次，避免让 Session Platform Owner 同时承担完整前端而成为瓶颈。

## 15. 集成里程碑

### Milestone 0：Contracts + Foundation

- 冻结共享领域类型和 REST/WS 协议。
- 完成错误码、correlation IDs、fixtures 和 fake adapters。
- 完成 Alembic 基线。

验收：四条工作流无需等待其他人的内部实现即可独立测试。

### Milestone 1：Fake-backed Vertical Slice

```text
Frontend
→ Session Platform
→ fake ContentPipeline
→ fake GameRuntime
→ PostgreSQL
```

验收：创建 session、导入课文、显示生成状态、选择角色、提交 command、收到 interaction、刷新恢复。

### Milestone 2：Real Core Integration

替换 fake ContentPipeline、GameRuntime、LLMGateway 和 RAG adapter，完成真实 Stage1 → Stage2 → Stage3。

### Milestone 3：Production Hardening

故障注入并验证：

- LLM timeout 和非法结构化输出；
- 搜索失败、恶意网页和抓取超时；
- DB transaction 失败；
- WebSocket 断开和 command 重发；
- 进程重启；
- snapshot 损坏；
- 事件 schema 版本不兼容。

只有 Milestone 3 通过后才称核心 MVP 完成。

## 16. 协作规则

- `dev` 始终保持可集成。
- 每个 GitHub Issue 使用短分支，不建立四个长期大分支。
- 一个 PR 对应一个可独立验收的逻辑单元。
- Shared Contracts、migration 和 protocol 需要双人 review。
- 每天至少一次集成到 `dev`。
- breaking contract change 先更新 schema/fixture，再迁移全部调用方。
- 采用干净切换，不保留长期兼容 shim。

建议代码所有权：

```text
backend/app/contracts/          全体共同 review
backend/app/core/               Developer A
backend/app/agents/runtime/     Developer A
backend/app/content/            Developer B
backend/app/research/           Developer B
backend/app/session/            Developer C
backend/app/api/                Developer C
backend/app/db/, models/        Developer C
backend/app/observability/      Developer C
frontend/                       Developer D
```

## 17. 核心质量门禁

### 功能

- 真实叙事课文可完成 Stage1 → Stage2 → Stage3。
- Stage 2 关键 beats 全部有原文证据。
- 三种交互模式真实生效。
- 刷新、断线和进程重启后恢复。
- 回溯保留旧历史并创建新活动分支。

### 工程

- Backend tests、lint 通过。
- Frontend lint、type check、production build 通过。
- PostgreSQL 集成测试在真实数据库运行，不允许长期 skip。
- 核心用户流程有 browser E2E。
- 故障注入覆盖外部 provider、DB、WS 和恢复链路。

### 内容质量

建立至少 5–10 篇不同叙事类型课文的 gold set，人工评估：

- 人物识别；
- 关键事件覆盖；
- 事件顺序；
- 原文证据引用；
- 角色一致性；
- Stage 2 偏离率；
- Stage 3 连贯性和收敛性。

## 18. GitHub Issue 拆分原则

在本设计复核通过后，按以下顺序创建 Issues：

1. Contracts + diagnostics foundation。
2. Gameplay Runtime command/step 重构。
3. Content ingestion + genre + evidence model。
4. PostgreSQL migration + branch/command/event transaction model。
5. SessionApplication + fake-backed REST/WS slice。
6. Frontend mock-backed core flow。
7. Open-web RAG adapter and security hardening。
8. Stage1 structured generation and validation。
9. Real core integration。
10. Recovery/rollback/fault-injection hardening。
11. Gold-set content evaluation。

依赖通过 GitHub issue dependencies 表达；每个 Issue 必须包含输入合同、输出合同、验收场景和非目标。
