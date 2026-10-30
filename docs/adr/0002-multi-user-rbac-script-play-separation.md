# ADR-0002 多用户账号体系、RBAC 与剧本创作/游玩分离

- 状态：已接受
- 日期：2026-09-15
- 关联：取代 `design_07` 的「用户体系当前零用例、仅留 AuthPort 接缝」结论；
  修订 `design_00`（单用户假设）、`design_04`（scripts/sessions 归属）、`design_06`（MVP 边界）

## 背景

核心 MVP（#2–#13）以「完全匿名单租户、无用户概念」交付：唯一归属单位是随机
`session_id`，所有 REST/WS 仅校验 UUID 是否存在，`scripts.session_id` 必填、
剧本无法跨会话复用。产品方向需要教师创作剧本、学生游玩，因此必须引入账号、
角色、剧本复用与创作/游玩分离。`design_07` 曾明确把用户体系登记为「当前零用例、
等第一个真实需求在组合根 seam 上补」——本 ADR 就是那个真实需求，正式落地该 seam。

## 决策

### 1. 多用户与组织（org）

- 新增 `orgs` 表；`users` 携带 `org_id + role`。
- 角色集合：`super_admin`（平台）/ `teacher` / `student`。
- **MVP 所有账号归属一个默认 org**；「多学校多组织」与学校 RBAC 为后续需求，
  但通过 `org_id` 预留隔离维度，避免以后全表迁移。
- 本 ADR 明确：`users.org_id + users.role` 单角色/单组织，不引入 membership 表；
  若将来出现「一人多组织/多角色」再演进。

### 2. 认证与会话

- 注册字段：邮箱或手机号 + 密码 + 昵称；**本期不做邮箱/短信验证**；登录标识全局唯一。
- 密码哈希：`argon2-cffi`。
- 会话：服务端 `auth_sessions`（Postgres，可撤销），HttpOnly / SameSite=Lax /
  生产 Secure，**14 天滑动过期**；登出撤销服务端会话。
- 状态变更 REST 使用 **CSRF double-submit**；WS 握手复用同一会话 Cookie，
  并校验目标 session 的 owner/org。
- 本期不做：改密、找回密码、账号停用、邮箱/短信验证。

### 3. 剧本（可复用实体）与剧情世界（游玩实例）分离

- 现有 `scripts` 表升级为**可复用剧本实体**：移除 `session_id` 必填，新增
  `owner_user_id`、`org_id`、`material_id`、`name`、`description`、
  `status(draft|published|unpublished)`、`visibility(org|public)`。
- `materials` 表保留并独立归属 `owner_user_id/org_id`；`scripts.material_id` 引用素材，
  **同一素材可生成多个剧本，彼此独立**。
- `sessions` 改为 `owner_user_id/org_id/script_id`：一局「剧情世界」= 某剧本的一次实例；
  `events` 为世界内消息，预留 `actor_user_id`，`sessions` 预留参与者以供将来多人同世界。
- 生命周期：`draft`（仅作者，可删除/重新生成）→ 显式发布 `published`
  （可见性 `org` 或 `public`）→ 可下架 `unpublished`（不再进库，存量世界可继续）。
  **发布后核心剧本内容不可变**；修改 = 重新生成新剧本。
- 权限：`teacher` 创作/发布/改可见性/可游玩；`student` 仅浏览（org + public）
  与游玩自己的世界；公开剧本**仅登录用户**可见可玩（跨 org）。

### 4. 异步生成与运行时取舍

- 生成（Stage1，实测 ~100s）走**进程内 asyncio 后台任务 + 内存进度**，前端轮询；
  **不落库**：进程重启丢在途生成，由教师重新生成。
- 因此 backend 保持**单 worker / 单实例**；「多 worker」不作为本期目标。
- 命令路径（游玩）保持**无状态**：每次命令从 DB（snapshot + events）重建运行时，
  不常驻内存，保证重启可恢复与内存可控。

### 5. usage 计量与运营后台

- 新增 `llm_usage`：**逐次 LLM 调用**一条记录
  （provider/model/prompt+completion+total tokens/purpose(stage1|agent|verify)/
  org/user/script/session/created_at）。
- 运营后台仅 `super_admin` 只读：剧本库列表 + 按 org/时间/用途的 token 聚合。
  教师不可见学生游玩数据。

### 6. 迁移

- 现有匿名测试数据无保留价值，采用**破坏式重建**：重设 Alembic 基线 +
  seed（`super_admin` + 默认 org「文境演示学校」+ 教师/学生测试账号）。
- 移除匿名会话创建入口。

## 后果

- 正向：产品闭环从「匿名单机 demo」变为「多用户 + 教师创作 + 学生游玩」；
  `org_id` 隔离与 AuthPort 落地，为后续学校 RBAC 留好演进路径；剧本复用避免学生
  重复承担 ~100s 生成与 token 成本。
- 负向（明确接受）：
  1. 无内容审查却允许公网可见，存在产品/合规风险，自担；
  2. 生成不持久化 → 重启丢在途生成；
  3. backend 单 worker，不与「多副本扩展」兼容；
  4. 无邮箱/短信验证、无改密/找回，账号安全性有限。
- 演进触发点：出现「多学校/多人同世界/多副本扩展」任一真实需求时，分别引入
  org 层级与 membership、参与者/广播机制、生成任务落库 + 队列。
