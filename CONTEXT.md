# 文境 — 领域术语表（CONTEXT.md）

> 单上下文布局（见 `docs/agents/domain.md`）。术语以本表为准；与 `design/` 旧文档冲突时，
> 以 ADR（`docs/adr/`）与本表为准。ADR-0002 引入的多用户术语见文末参考。

## 产品域

### 课文（Material / 课文素材）

教师导入的语文课文原文（戏剧/小说/叙事文）及其分析输出。
独立归属实体，落 `materials` 表（`owner_user_id` / `org_id`，JSONB）。
同一篇课文素材可生成多个剧本，彼此独立。契约：`contracts/material.py`。

### 剧本（Script）

**可复用的创作实体**，由课文素材经 Stage1 生成（`ScriptPackage`），落 `scripts` 表。
不再绑定游玩会话（ADR-0002 移除 `session_id` 必填），可被多局「剧情世界」引用。
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
