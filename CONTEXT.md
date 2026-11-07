# 文境 — 领域术语表（CONTEXT.md）

> 单上下文布局（见 `docs/agents/domain.md`）。术语以本表为准；多用户相关术语见文末参考。

## 产品域

### 课文（Material / 课文素材）

教师导入的语文课文原文（戏剧/小说/叙事文）及其分析输出。
独立归属实体，落 `materials` 表（`owner_user_id` / `org_id`，JSONB）。
同一篇课文素材可生成多个剧本，彼此独立。契约：`contracts/material.py`。

### 剧本（Script）

**可复用的创作实体**，由课文素材经 Stage1 生成（`ScriptPackage`），落 `scripts` 表。
不再绑定游玩会话（多用户化改造移除 `session_id` 必填），可被多局「剧情世界」引用。
归属 `owner_user_id` / `org_id`，引用 `material_id`。
生命周期状态：`draft`（草稿）→ `published`（已发布）→ `unpublished`（已下架）。
**发布后核心剧本内容不可变**；修改 = 重新生成新剧本（改可见性除外）。

### 剧情世界（Session / 游玩实例）

某剧本的**一局游玩实例**，落 `sessions` 表（`owner_user_id` / `org_id` / `script_id`）。
玩家在其中选角、推进剧情、回溯分支；`events` 为世界内消息，`snapshots` 为状态快照。
⚠️ 代码中 `session` 一词有二义：`sessions` 表指**剧情世界**（游玩实例）；
`auth_sessions` 表指**登录会话**（认证凭据，见下）。文档中「世界」优先指前者。

### 登录会话（Auth Session）

服务端认证会话，落 `auth_sessions` 表，14 天滑动过期，可撤销。
与「剧情世界」无关系；HttpOnly Cookie `wenjing_session` 承载其 id。

### 发布（Publish）

剧本生命周期动作：`draft` → `published`。发布使剧本进入可游玩库
（org 内或公开，取决于可见性）。反向动作为**下架**（Unpublish）：
`published` → `unpublished`，不再进库，但**存量剧情世界可继续游玩**。
重新发布允许 `unpublished` → `published`。

### 可见性（Visibility）

已发布剧本的可见范围：`org`（仅同组织用户）| `public`（所有登录用户，跨 org）。
发布后仍可修改可见性（这是发布后唯一允许的内容维度变更）。
公开剧本仅登录用户可见可玩（无匿名访问）。

## 用户与组织

### 组织（Org）

账号归属与资源隔离单位，落 `orgs` 表。MVP 所有账号归属一个默认 org
（seed：「文境演示学校」）；`org_id` 为将来多学校隔离预留的维度。
剧本 / 素材 / 剧情世界 / LLM 用量均按 org 归属。

### 角色（Role）

用户全局单角色（`users.role`，无 membership 表）：

- **super_admin（平台管理员）**：只读运营后台（剧本库、token 用量聚合）。
- **教师（teacher）**：创作 / 发布 / 下架 / 改可见性剧本；可游玩。
- **学生（student）**：浏览（org + public）剧本广场并游玩；不参与创作。

教师不可见学生游玩数据；非 super_admin 不可进入运营后台。

### 用量（LLM Usage）

每次 LLM 调用一条记录，落 `llm_usage` 表
（provider / model / tokens / purpose: stage1|agent|verify / org / user / script / session）。
供 super_admin 运营后台按 org / 时间 / 用途聚合。
媒体（图片/TTS/ASR）另记 `media_usage`（kind / provider / units / org / script / session），
与 token 语义的 `llm_usage` 分离。

## 媒体与场景表现

### 资产（Asset）

场景背景图 / 角色头像 / 立绘等多媒体文件。字节存**对象存储**（S3 兼容，私有桶），
DB 只存元数据；契约只放稳定引用 `AssetRef{asset_id, kind, status}`，不存 URL/字节。
访问经鉴权端点签发短时效预签名 URL，前端直取。发布后资产冻结。

### 场景设计（SceneDesigner）

场景资产编排组件（`domain/game/media.py`）：**画师层转写 → 文生图 → 存储 → 产出
`AssetRef`**（画师优先，自动配图不再检索素材库）；检索只在教师显式「检索替换」
（`search_replace=True`）时启用。Stage2 在剧本生成期预生成；Stage3 由引擎
中转异步生成。

### 画师层（Painter / PromptWriter）

`domain/game/prompt_writer.py`：把节拍文本 + 人物外貌锚点 + 视觉备注转写为「画面
主体描述」的 LLM 层。画风段（`DEFAULT_STYLE`：课本插画/中国水墨意韵/手绘/非照片写实，
可配 `WENJING_MEDIA_IMAGE_GEN_STYLE`）与构图尾巴由 `build_generation_prompt` 确定性
追加；转写失败回退确定性描述（场景永远有图）。

### 编剧 Agent / DM

编剧 Agent（`screenwriter`）是剧情推进的"主持人"角色；"DM"仅口语别名，不是独立术语，
代码与契约沿用 `screenwriter`。

### 还原（Stage2 珊瑚图）

Stage2 是**纯 IO 的珊瑚形还原**（设计见 `docs/design/play-through-redesign.md` §A）：
主干场景顺序播放，场景的 `options`（`SceneOption`）指向分支（`BranchScene`）、
下一场景或结局（`Ending`）；非主分支播完按 `return_mode` 回主干——`choice` 回决策点、
`continue` 续接下一场，带 `ending_id` 的分支是终局。台词在生成期预写成
`Beat.dialogue`（`DialogueLine`，`speaker=None` 为旁白），游玩期零 LLM。
无 `options/dialogue` 的旧剧本走运行期 agent 的线性路径。**还原期禁用自由输入**
（`free_input` 只属于续写阶段）。

### 探索（Exploration / Stage3 地图）

续写阶段的地点抽象（设计 §B3）：`ExplorationMap` 给出起点与地点表
（`ExplorationLocation`：`location_key`/`title`/`participants`/`visual_summary`/
`scheduled_facts`），运行时用 `loc:{location_key}` 作场景键。**在场是唯一事实源**：
地点的 `participants` ∩ 已创建角色 = 此刻在场的人，只有他们提议/回应。
每轮玩家动作先做**确定性结算**（`exploration_settle`：地点化摘要 + 处境，零 LLM），
再由在场 NPC 反应；**换景**用 `switch_scene` 命令前进式切换
（`scene_switch` 事件，不建事件分支，交互点带 `scene_options`）。旧剧本没有地图，
维持原 3 轮 agent 行为。解锁新场景 / 未连通地点随 M6 的 Producer 落地。

### 参演与工作人员（Cast / Staff）

Stage3 的 agent 分工（设计 §B1）：**参演**是 `CharacterAgent`（NPC）与人类玩家，
出场、写台词、进 `speech_log`；**工作人员**是 `DirectorAgent`（设计玩家选项）、
`ProducerAgent`（解析玩家干涉）、`PainterAgent`/`VerifierAgent`/`ScreenwriterAgent`
（既有能力），不出场、不写角色台词，输出只进系统事件/选项/资产。

### 干涉（Intervene）

Stage3 玩家用自然语言改变世界的命令（`intervene` + `IntervenePayload`）：
建场景、从角色池拉人、新增角色（契约已就位；`ProducerAgent` 落地后该命令才进入
Stage3 允许列表）。`ProducerAgent` 解析为结构化意图并做 canon/预算
校验，应用结果全部事件化（`scene_created`/`character_created` 等），因此**可回溯**——
回到创建之前，该场景/角色等于从未存在。离线期间 NPC 自主行动（§B6），回来只给
`offline_hint` 提示并指路时间线。

### 回溯（Rollback）与回溯页

回溯是**保留历史的分支切换**：`rollback_to_event`（payload 为目标事件在活动分支上的
`sequence`）让引擎新建活动分支，继承前缀**止于目标所属叙事拍之前**——目标拍由新分支
整拍重演（继承它会让恢复时的重放把同一拍计两次）；旧事件仍可审计
（`EventStore.rollback_to`）。可回溯的目标是含有叙事拍的节点（台词/系统提示等中途事件
按其所属拍处理；首拍之前没有合法目标）。回溯后阶段、beat 游标、剧情日志与角色记忆
全部随事件回退——记忆由事件折叠重建（`CharacterAgentManager.derive_memories`），
不受进程内状态影响。

回溯页（`/game/rollback`）数据源是 `GET /api/sessions/{id}/timeline`，只投影
`active_events()`——剧本里**尚未演到**的场景与被放弃分支的进度都不会出现；每一幕带
场景图与一句节拍描述（事件溯源是资产与进度的唯一权威）。

### 流式（Streaming）

运行期角色发言采用真 token 流式以降低 TTFT；`stream_*` 为 WS 瞬态消息，事件溯源只存
最终完整文本，断线用 `resync` 补全。
