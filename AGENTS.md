# Wenjing — Agent Instructions

语文课文情景演绎 multi-agent 平台（FastAPI + Next.js），ADR 驱动。**规格优先级**：`docs/adr/`（最新）> GitHub Issue/spec > `docs/archive/design/`（MVP 期归档背景，**不是现行规格**）。文档地图见 `docs/README.md`，术语以 `CONTEXT.md` 为准——动手前先读相关 ADR。

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

### 事件溯源

事件是权威。`EventStore.active_events()`（当前活动分支）与 `branch_path()` 共同决定状态与**资产继承**；`RuntimeAssets.rebuild(store)` 是从事件重建场景资产索引的指定入口、**不落库**（`domain/game/assets.py`）——注意生产侧目前无人调用它，接线在 #56（命令外事件路径）。

### 剧本生成 workflow（ADR-0003）

```
collect_materials → verify_materials → [materials_gate] → divide_events
  → design_characters ⇉ Send 扇出 N → design_one_character×N → merge_characters(join)
  → [pre_write_gate] → write_script → final_audit → design_assets → [final_gate] → END
  （reject 按重试预算打回；耗尽 → fail）
```

配图在总审**之后**（#48 选项 A：不为一篇可能被打回的剧本付图片钱）；教师对配图槽位的四操作（重新生成/检索替换/上传/删除）经 `GateEdits.asset_ops` 随 final_gate 的 approve 生效（#49）——reject 路径忽略 ops，重写后 design_assets 重跑。

教师闸门靠 `interrupt()` 暂停、`Command(resume=directives)` 恢复，**必须**有 AsyncPostgresSaver checkpointer 才启用。注意这层耦合：没有 `WENJING_LLM_API_KEY` 就没有 checkpointer，`workflow_enabled=False`、闸门不启用，生成退回旧确定性合成路径（仅测试/E2E 依赖，随 #33 退役）——生产链路只走 workflow + 真实 LLM。

## 陷阱与约定

**`make test` 会清空所连的库**：集成测试结束 `drop_all` 全部业务表并删 `alembic_version`（`tests/conftest.py`），交还空库。别对想留数据的库跑；跑了补 `make migrate && make seed`。手动起后端**不会**自动迁移（只有生产入口默认 `alembic upgrade head`）。

**外部依赖不可用时集成测试静默 skip**，**全绿不代表跑过**。两类：PostgreSQL（`test_db_event_store`、`test_migrations`、`test_full_flow`、`test_api_sessions` 等）→ 先 `make db-up && make migrate`；MinIO（`test_media_storage.py` 的对象存储集成用例）→ 先 `make media-up`。只有 MinIO 这类有 `WENJING_TEST_MINIO=1` 把静默跳过变成硬失败（CI 用它）；PG 那类没有这个开关，库没起就是纯绿。

**后端必须单 worker**：会话运行时、WS outbox、在途生成都是进程内存 / asyncio 任务状态。多 worker 或多副本的后果与运维细节见 `README.md` 生产部署一节。

**新增错误码要同时登记五处**，漏任何一处都不报错、只静默降级（errx 用法见 `infrastructure/errx/__init__.py`）：

1. `infrastructure/errx/codes.py`：整数常量（按模块分段，段内连续）
2. 同文件 `register_all()`：`register(CODE, "模板 {reason}", is_affect_stability=…)`——模板用于服务端日志与服务端消息。注意 `is_affect_stability` 只是挂在 `Error` 上的标记，**当前无人消费**，它**不是**对外 `retryable` 的来源
3. `contracts/errors.py::STABLE_CODES`：`"DOMAIN_NAME": (ErrorDomain.X, retryable)`——**只有 `retryable` 是 load-bearing 的**。元组里的 `ErrorDomain.X` 当前被丢弃（`envelope_for` 写的是 `_domain, retryable = stable_code(...)`，domain 改由码名前缀现推），所以域写错**不报错、只静默失效**；真正会炸的是**前缀不是合法 `ErrorDomain` 值**——`ErrorDomain("<prefix>")` 抛 `ValueError`
4. `infrastructure/diagnostics/errors.py::_CODE_MAP`：整数码 → 稳定码名。**漏了对外信封回落 `INTERNAL_ERROR`**
5. 同文件 `safe_message`：整数码 → 用户可见中文。**漏了用户只看到「服务内部错误」**

**改代码里的 prompt 文本对已 seed 的库不生效**：system/准则/判据类文案存 `prompts` 表，键为 `(stage, node, version, section)`，代码默认在 `domain/prompts/defaults.py`，DB 无行/禁用/异常时回退默认。DB 覆盖行按 version 匹配，所以**必须升 `VERSION`** 才会落到新键上并回退到新默认；`make seed` 只幂等补新行，不覆盖已启用行。字段类型说明类文本（`_OUTPUT_CONTRACT`）留在代码、不落库。

**契约单源四处，但只有三处受保护**：`backend/app/contracts/`（Pydantic，唯一事实源）→ `contracts/fixtures/`（**手工维护的样例载荷**，不是生成物）→ `contracts/jsonschema/`（`scripts/export_contracts.py` 的导出产物）→ `frontend/src/lib/contracts/types.ts`（手工镜像）。改契约后跑 `cd backend && uv run python -m scripts.export_contracts`；`tests/test_contracts.py` 断言导出与 fixtures 都不过期，但**完全不管 `types.ts`**——它没有生成器，得自己同步。流程见 `docs/contract-change-process.md`。

**测试约定**：`asyncio_mode = "auto"`（async 测试不用加 `@pytest.mark.asyncio`）；HTTP 打桩用 `httpx.MockTransport`；联网 / 真实 LLM 测试按 env 门控（无 key `pytest.skip`，开关如 `WENJING_TEST_IMAGE_SEARCH=1`）；`caplog` 在整套跑时不可靠，测日志用 monkeypatch 把模块 `logger` 换成自建 probe（见 `tests/test_rag.py::_ProbeLogger`）。

**配置一律走 `infrastructure/config.py`**（pydantic-settings，env 前缀 `WENJING_`）；完整可选项见 `backend/.env.example`，provider 选 `null` 时对应端口是安全空实现。

## Agent skills

- Issue tracker：GitHub Issues，用 `gh` CLI。见 `docs/agents/issue-tracker.md`。
- Triage labels：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。
- Domain docs：单上下文布局，`CONTEXT.md` 在仓库根、ADR 在 `docs/adr/`。见 `docs/agents/domain.md`。

### 回复语言

回复用户时的最终总结部分请使用中文。
