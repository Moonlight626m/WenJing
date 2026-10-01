# ADR-0005 场景视觉化与多媒体：对象存储、可插拔媒体端口、生成期/运行期生图与流式音频

- 状态：已接受（2026-09-22 grilling 决策；同日经 `codebase-design` 评审修订 B1–B5 等）
- 日期：2026-09-22
- 执行跟踪：epic #38，tickets #39–#64（见 `docs/design/media-scene-visualization.md` 附录映射）
- 关联：ADR-0003（生成期不做逐 token 流式，本 ADR 对**运行期**修订之）、
  ADR-0004（运行期角色 Agent 工具化，本 ADR §10 处理其流式兼容）、
  issue #36（契约 breaking 升级，前置）、#21（命令路径无状态化 + 乐观锁 CAS，本 ADR §5 需兼容）、
  `docs/archive/design/design_07_session_manager_and_infra_seams.md`（`StoragePort` 接缝，已过期）、
  `docs/research/jd-cloud-deployment.md`（OSS 选型）、
  `docs/design/media-scene-visualization.md`（讨论纪要 + 评审修订 + 落地计划）

## 背景

当前系统只有"文本 + JSONB 落 PostgreSQL"一种持久化，没有二进制/对象存储、文件表、
上传通道或静态资源服务。产品要给剧本场景加 **galgame 式背景图**（Stage2 还原用现成/
开放版权素材，Stage3 续写无现成素材需文生图），并持续产生多媒体文件。现有存储结构性不足。

经多轮 grilling 与一轮 `codebase-design` 评审，明确了形态、时机、来源、端口、存储、
流式与音频架构，并修正了"把当前运行时模型不支持的事当成已解决"的若干处。

## 决策

### 1. 表现形态：轻量沉浸（背景图 + 底部字幕），头像归详情页

- 游玩内：全屏 `scene.background_asset` 铺底 + 屏幕中下方流式字幕（**无气泡框**），
  角色行 `角色:xxx`，旁白居中斜体；场景切换背景淡入 + 短暂场景标题。
- 多行字幕上限 3 行、到达顺序堆叠、流结束停留 2–3s 淡出、溢出排队、同 speaker 新句替换旧句。
- **头像/立绘只用于剧本详情页**；游玩内不显示头像，场景互动靠背景图表达。
- 只做静图，不做动效；分层立绘舞台留待未来。

### 2. 媒体端口与分层：domain 管接口/Mgr，infra 放实现

- **端口**（domain 侧简单接口，infra 实现）：
  - `ObjectStoragePort`（put / presign；`delete` 待生命周期立项再定义；`get` 仅 infra 内部用于处理）
  - `ImageGenPort`（文生图，外部 provider）
  - `ImageSearchPort`（开放版权库检索，返回候选 + 许可元数据）
  - `AssetRepositoryPort`（save / get_by_id / find_by_dedup_key：**资产元数据与缓存查询**）
  - `MediaMeterPort`（best-effort 计量，仿 `UsageRecorder`）
  - `MediaQuotaPort`（**付费调用前**的 check + consume；与计量分离，不可用 best-effort recorder 兼任）
- 图片多规格/转码不塞进 `ObjectStoragePort`，由 infra 的 `ImageProcessor` 承担（出现第二个后端再抽象）。
- 流式/媒体**编排放在 `domain/game/` 下独立文件**（如 `game/media.py`、`game/streaming.py`），
  与游戏运行时同层但职责分离；**不新增 `domain/engine`**。
- 具体适配器放 `infrastructure/media/`（S3、ImageGen provider、Openverse/Wikimedia…），
  严守 `domain 不 import infrastructure`（`make lint-arch` 守卫）。
- `TtsPort`/`AsrPort` 本次**不建代码端口**，仅在本文档登记为 M6 扩展点（避免投机接口）。

### 3. 稳定引用与 URL 物化：契约 URL-free

- 契约与投影**只放稳定引用，字节与 URL 都不进契约/DB**：
  `AssetRef{asset_id: UUID, kind: Literal["background","avatar","fullbody"], status: Literal["pending","ready","failed"]}`。
- `object_key` 只存在于 `assets` 表与 `ObjectStoragePort` 内部；署名另设
  `AssetCredit{author, license, source_url, license_url}`（§6）。
- **预签名 URL 不在投影层物化**（`session_projection` 保持纯同步纯函数）：
  新增鉴权端点 `GET /api/assets/{asset_id}/url`，校验 actor 对 session/script/org 的访问权后
  返回短时效预签名 URL；前端按过期时间缓存。游玩内背景通过 `RuntimeState` 的稳定引用获取 URL。

### 4. 存储：S3 兼容对象存储 + 元数据入库 + 一致性顺序

- 统一 S3 协议（`ObjectStoragePort` + S3 adapter）：开发 MinIO、生产京东云 OSS（选型延后）。
- 私有桶；预签名经 §3 鉴权端点签发；**已存图片前端直取对象存储**（不后端代理流量）。
- **DB 与对象存储无法原子**，固定顺序：先落 `assets` 行 `status=pending` → 上传对象 →
  标 `ready`（失败标 `failed`）。崩溃恢复见 §5。
- 生成/上传时产出 `thumb/medium/original` 多规格 + WebP/AVIF。
- **发布即冻结资产**；重新生成产生新版本；引用语义（pinned vs latest）在实现期定（见待定项）。
  删除/回收暂不考虑。

### 5. 生成时机与"命令之外的领域事件"

- Stage2（还原）：script-gen workflow 内**离线预生成**；Stage3（续写）：**运行期实时生成**。
- **触发者是 `GameRuntime`，不是编剧 Agent**：编剧是确定性逻辑（ADR-0004 后果），
  新场景出现时由引擎发起 `scene_asset_request`，调 `SceneDesigner` 后台生成；
  叙事先行（占位/纯文本），完成后替换。
- **命令之外的领域事件必须有一等公民落库路径**（现状事件只在命令事务内、带 CAS，见
  `services/session_store.py` 的 `SessionStore.commit`，ADR-0006）：新增
  `SessionApplication.report_runtime_event(...)` /
  `report_asset_ready(session_id, branch_id, scene_key, asset_id)`：新建 store、经
  `SessionStore.commit()` 复用同一 CAS 拼写落库、**不带 player command**；落库前校验 branch
  仍为 active，否则 no-op；**后台任务不得持有 `GameRuntime`**，请求期把 `branch/scene` 绑定进任务。
- **Stage2 资产节点幂等**（workflow resume/容错会重跑，ADR-0003 §2）：SceneDesigner 以
  `(script_id, scene_id, purpose, style, provider_version)` 为键幂等，命中即跳过；付费调用前
  先落"生成意图"票据。
- **单 worker 崩溃恢复**：`asset_jobs` 表记录在途任务，启动时重排 pending，或 pending 超 TTL
  降级 `failed` 允许重试；避免占位图永挂。

### 6. 来源策略：开放版权抓取优先 + 审核 agent + 回退生成（含署名合规）

- Stage2：`ImageSearchPort`（首发 Openverse + Wikimedia Commons，带许可元数据）→ 审核 agent
  （便宜模型 + 结构化输出，判"相关/画质/许可"）→ 不合格回退 `ImageGenPort`；保留"纯生成"开关。
- Stage3：**只生成**；检索仅作教师手动替换项。
- 背景图不含人物、统一画风/比例（16:9）；头像 1:1 单独生成（每角色一次，跨场景复用）。
- **署名合规（修订 Q22/Q26）**：CC BY / CC BY-SA 要求向最终用户署名。
  - 默认**仅采用免署名许可**（CC0 / Public Domain），学生端无需展示；
  - 若采用需署名许可，则**学生端必须展示折叠署名**（`AssetCredit`），不得只给教师端；
  - 教师上传内容需审核；本地过滤排除与教育分发不兼容的许可。
- 去重键：`(org_id, scene_key/character_name, 归一化描述摘要, style, provider_version)`，
  **按 org 作用域**，避免跨 org 越权复用。

### 7. 审批：生成期不介入，场景阶段完成后审批，自由探索不审批

- script-gen 场景阶段完成后，在 **pre_write gate** 内启用配图审批（每项默认 1 张自动图，
  教师可"重新生成/检索替换/上传自有/删除"），不默认出多候选。
- 成本控制：惰性生成或每剧本上限；先出成本预览；`media_usage` 聚合出 org 预算 +
  付费前配额闸（§2 `MediaQuotaPort`）。
- 运行时安全：provider 侧审核 + 本地过滤，失败降级占位；每会话生图上限（config），
  先计量后硬配额。

### 8. 契约与状态（等 #36 合并后落地）

- `Scene.background_asset: AssetRef | None`；
  `CharacterProfile.avatar_asset / fullbody_asset: AssetRef | None`（详情页用）。
- **`scene_key` 进入显式状态与事件**（否则重连/重放背景丢失）：
  `_RState.scene_key: str`（脚本场景 `scene:{scene_id}`，运行期新场景 session 内单调 key），
  写进 `export_state`/`restore`，并放进 `plot_advancement` 事件 payload；`_replay_event` 据此重建。
- `RuntimeState`：保留 `scene_id: int | None`（Stage2 脚本场景）并新增 `scene_key: str | None`；
  新增 `current_asset: AssetRef | None`（由 `export_state()` 在引擎内解析，那里同时有 script 与 events，
  投影层保持纯函数）。
- `asset_ready` 进 `EventType`、`_EVENT_TYPE_MAP`/消息类别与前端 TS。
- 走四处单源流程（Pydantic → fixtures → jsonschema → 前端 TS）与 `test_contracts.py`。

### 9. 事件溯源是资产继承的唯一权威

- **不新增第二套"分支前缀继承"**：场景资产由 `EventStore.active_events()` 重放派生，
  与 stage/beat/direction 同构（复用 `branch_path`/快照/回溯语义）。
- `runtime_assets` 若保留，**降级为可从事件重建的非权威索引/缓存**，并明确标注。

### 10. 流式：真 token 流式（修订 ADR-0003 对运行期的结论）

- 为降 TTFT，运行期角色发言采用真 token 流式。
- `LLMService` 增加 `astream`；`WenjingChatModel` 实现 `_astream` 使 LangChain agent 自动支持。
- **与工具调用 agent 的兼容策略（ADR-0004）**：只向下游发出 `content` 增量，
  忽略 `tool_call_chunks`（工具轮通常无可见 content）；若某轮先输出引导语再以 tool_calls 收尾，
  该引导语视为**临时（provisional）**，由最终持久 `character_speech` 覆盖（§终态规则）。
  若 provider 频繁产生前置引导语，退化为"工具轮非流式 + 最终答复流式"的两阶段实现。
- 事件溯源不变：**事件流只存最终完整文本**；`stream_*` 为 WS 瞬态消息，不参与 `seq`/重放；
  断线用 `resync` 补完整消息；`command_id` 幂等不变。
- **终态规则**：前端收到该发言的持久 `character_speech`（带 seq）即丢弃对应流缓冲。
- **背压/取消**：per-connection 流式会话；disconnect 即 cancel；有限缓冲 + drop-oldest。
- 计量：每次 LLM 往返单独记一条（保持 ADR-0004 §4），流末按 provider usage 或估算。
- tee 编排：`LLM 文本流 → {WS 文本消费者, 分句器 → TTS → 音频出口}`；多角色并发生成、
  增量带 `speaker`，前端按去向路由。
- **TTFT 顺序**：reaction 的流式在 cycle 中位于 propose/verify 之前（`_on_input` 先
  `_collect_reactions`），需在实现时确认可见 token 不被内部 silent 阶段阻塞。

> 实现注记（2026-10-01，#59/#60/#62 落地时澄清，不改变上述决策）：
> - 「忽略 `tool_call_chunks`」指的是**不把它当可见文本下发**，不是不产出。LangGraph
>   的工具节点靠 `AIMessageChunk.tool_call_chunks` 组装 tool_calls，丢掉它工具轮永远
>   不触发（ADR-0004）。同一条增量里的 `content` 与工具分片分属两条通道，各自照发。
> - `disconnect 即 cancel` 取消的是**该连接的瞬态流**（`StreamChannel` 发送失败即停）。
>   命令与它的 LLM 往返照常跑完并落库：半途取消会留下一次没有 `character_speech`
>   的命令，重连的玩家再也看不到那句台词——与「事件只存最终完整文本」相冲突。
> - 有限缓冲 + drop-oldest 落在**连接级**出口（`StreamChannel`），淘汰只针对字幕增量；
>   `stream_start` / `stream_end` 是协议骨架，挤掉 `stream_end` 会让前端留一条永不
>   收束的字幕。

### 11. 音频：并发音轨、后端中转、不混音、客户端打断

- 音频可并发；**后端不混音**，按 speaker 各推一条流。
- 协议：`audio_start{track_id, speaker, codec, sample_rate}` → 二进制帧 → `audio_end{track_id}`
  → `cancel_audio{track_id}`；前端多 `<audio>` 并发播放。
- 音频经后端中转（鉴权 + `media_usage` 统计）——与已存图片"前端直取"是两类资源（即时合成需中转）。
- **barge-in 收敛为客户端行为**：停播 + `cancel_audio{track_id}` 取消 per-connection TTS 任务；
  **不抢占 LLM**（命令仍串行、事件同事务持久化，服务端无法在生成中接收新命令）。
- 本次只做端口与编排骨架；TTS 实现单独立项（M6）。

> 实现注记（2026-10-01，#63 落地时澄清，不改变上述决策）：
> - **一条音轨的帧在流上连续**，两条轨之间才交错。二进制帧不带 `track_id`
>   （上面的协议形状就是 `audio_start` → 帧 → `audio_end`），所以"帧归谁"完全
>   依赖这条不变量：前端只能把帧归给"最近开启且未收尾"的那条轨。服务端由
>   `TtsSynthesizer` 保证——同一条轨的 start/chunk/end 之间没有 `await`，在事件
>   循环里是原子的。两侧各有用例钉住（`test_tts.py` / `audio.spec.ts`）。
> - **音频只在 `null` provider 下静默跳过**：`TtsSynthesizer` 收到空字节即不开音轨，
>   字幕照滚。所以无 key 的开发环境没有配音，但不是故障。
> - **服务端的 `cancel_audio` 基本是空操作**：命令串行 + WS 接收循环在命令期间不读
>   新消息，客户端发不出"生成中途"的取消。barge-in 的实质是客户端 `stopAll()`；
>   服务端那句只是把还没发完的帧丢掉，收效有限但无害。

### 12. 计量与配额：新建 `media_usage`，不引入 Mongo

- 新建 `media_usage`（`kind=image|tts|asr`、provider、model、units（张/字符/秒）、size、
  org/user/script/session、`meta` JSONB）；归属上下文仿 `UsageContext`；best-effort。
- **配额与计量分离**：`MediaQuotaPort` 在付费调用前 check+consume。
- `llm_usage` 保持 token 语义不动；**不引入 MongoDB**（技术栈全 Postgres，JSONB 满足业务化组织）。
- 补充 media 错误域与可观测指标（缓存命中率、生图延迟、失败率、provider 错误）。

### 13. 术语

- 沿用"编剧 Agent / screenwriter"作为 DM 角色；新增 **SceneDesigner**（场景资产编排组件）
  并写入 `CONTEXT.md`。

## 后果

- 现有"文本 + JSONB"存储补齐对象存储与媒体端口；单 worker/单实例约束不变。
- 新增依赖：S3 SDK（如 `aioboto3`/`boto3`）、图片处理库；生图/TTS provider 走外部 API。
- 契约 breaking 变更需等 #36，且走四处单源流程。
- 运行期外部生图/流式引入延迟与失败面：以"占位先行 + 异步替换 + 上限 + 安全过滤 + 崩溃恢复"兜底。
- **新增"命令之外的领域事件"落库路径**，是本次对运行时模型的实质扩展（影响 #21 相关代码）。
- 本地开发需引入 MinIO（compose + bucket 初始化 + CORS + 内外网 endpoint 分离）。

## 待定项（非阻塞）

- 对象存储厂商（京东云 OSS vs 腾讯 COS）、桶策略/CDN、URL TTL、多规格尺寸。
- `ImageGenPort` / `TtsPort` 首个 provider 选型。
- 开放版权库素材质量评估（决定 Stage2 抓取 vs 生成的默认权重）。
- 资产生命周期与回收（发布冻结后删除/孤儿/TTL 策略）、`assets.version` 的 pinned/latest 语义。
- 流式/TTS 的 provider 用量回报格式（`include_usage` / 音频时长）。
