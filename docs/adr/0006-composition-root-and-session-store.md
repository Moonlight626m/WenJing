# ADR-0006 后端组合根与 SessionStore 深模块：收敛分散装配与会话持久化接缝

- 状态：已接受
- 日期：2026-09-28
- 关联：AGENTS.md「后端分层与依赖方向」、`backend/.importlinter`、
  ADR-0005 §5（命令之外的领域事件路径）、epic #38（tickets #39–#64）、
  `docs/archive/design/design_07_session_manager_and_infra_seams.md`（组合根 seam 的早期设想，已归档）、
  `codebase-design`（深模块 / 接缝词汇）

## 背景

MVP 演进到多用户 + 剧本 workflow 后，后端出现两处结构性负担：

1. **组合根散落在各 controller**：`routes.get_application`、`scripts.get_script_library`、
   `admin.get_admin_service`、`auth_deps.get_auth_service` 各自持有模块级单例并就地装配
   LLM / RAG / UsageRecorder；`main.lifespan` 还经 `set_generation_checkpointer` 反向 set
   一个 controller 全局。ADR-0005 要一次性接入 6 个媒体端口（#39–#47），每处都会再抄一遍。
2. **会话持久化逻辑宽而重复**：`services/session_runtime.py` 的 `SessionApplication`
   同时承担访问控制、用例编排、投影、WS 协议支撑与事务拼写；乐观锁 CAS 单事务在
   `_persist_command` 与 `_commit_system_events` 中重复两遍。ADR-0005 §5 的
   `report_runtime_event` / `report_asset_ready`（#55/#56）将是第三条相同拼写。

## 决策

### 1. 唯一组合根 `app/composition.py`

- 新增 `Container` + `get_container()` / `reset_container()`，作为**唯一**依赖装配点；
  `Container` 惰性构建并按需缓存 `SessionApplication` / `ScriptLibrary` / `AuthService` /
  `AdminService` 及 LLM / RAG / usage 适配器。
- lifespan 改为 `container.open()` / `container.close()`：事件循环绑定资源
  （LangGraph checkpointer）由组合根持有，删除 `set_generation_checkpointer` 与
  main→controller 的反向注入。
- controller 经 `get_container().xxx` 取服务，**不再建模块级单例**。
- `Container` 位于 controllers 之上、services/infrastructure 之下，只 import
  services/domain/infrastructure；新增 import-linter 契约 `composition_is_outer`
  守卫（domain/services/infrastructure/contracts 不得反向 import `composition`）。

### 2. 会话持久化深模块 `services/session_store.py`

- 抽出 `SessionStore`，接口收窄为
  `restore` / `commit` / `load_package` / `has_command` / `discard`：
  - `restore`：锁定会话行一致读取 (version, 剧本包, 快照, 事件流)；
  - `commit`：事件 + 命令 + head/branch/stage/快照单事务，内含乐观锁 CAS
    （`UPDATE ... WHERE version = expected`，冲突 `SESS_CONFLICT`，DB 失败 `PER_WRITE_FAILED`）；
  - `discard`：初始化失败的补偿删除。
- **命令路径与 `initialize_session` 共用 `commit()`**；ADR-0005 §5 的命令外事件路径
  （#55/#56）直接复用同一 CAS 拼写，无需另起实现。
- `SessionApplication` 随之变薄，只保留用例编排、访问控制与投影。

## 后果

- 媒体端口（#39–#47）与流式（#58–#64）的接线集中在组合根一处，新增端口只改一个文件。
- M4 命令外事件路径不再复制 CAS；并发语义、快照条件、错误码保持原样。
- `services/session_runtime.py` 由 633 行降至约 460 行；`SessionStore` 成为可独立单测的接缝。
- 单 worker / 单实例约束不变；lifespan 仍负责 checkpointer 的建与释放。

## 未决 / 后续

- **WS 通道抽取**：`controllers/routes.py` 的 per-connection outbox / confirm / resync
  将被 M4 `asset_ready`、M5 `stream_*`、M6 音频撑大，计划抽 `SessionChannel`（另一里程碑）。
- **媒体领域接缝落点**：`SceneDesigner` 与媒体端口在 `domain/game/` 还是跨 Stage2/3 的
  `domain/media/`，随 #39（M0 端口骨架）确定。
