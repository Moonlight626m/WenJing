# Wenjing — Agent Instructions

语文课文情景演绎 multi-agent 平台（FastAPI + Next.js）。动手前先读 `design/` 中对应模块的设计文档（`design.md`、`design_00_tech_decisions.md`、`design_0X_*`）。**注意：`design/` 是 MVP 时期的文档，很多内容后期都会升级，只作背景参考，不是现行规格**；若与后续演进冲突，以更新者为准，优先级大致为 `docs/adr/`（最新）> GitHub issue/spec > `design/`。

## 实现工作流

- 完成新功能/修复后，**开 subagent 用 `code-review` skill 审查改动**，修复发现的问题（如有）再向用户汇报。

## 常用命令

命令在仓库根用 Makefile 封装；后端在 `backend/` 用 uv，前端在 `frontend/` 用 npm。

```bash
make dev            # 起 db + 迁移 + backend(:8000) + frontend(:3000)，后台，日志 .run/logs/
make dev-stop       # 停止；make dev-status 查看状态
make migrate        # Alembic upgrade head
make seed           # 默认 org + super_admin/teacher/student 测试账号（幂等）
make db-reset       # 破坏式重建本地库：删卷 → 迁移 → seed（旧数据不可恢复）
make test           # backend pytest（PG 可用时含集成测试）
make lint           # backend ruff + frontend eslint（不含类型检查）
make e2e            # Playwright（需 backend+frontend 已运行）
```

- 单个测试：`cd backend && uv run pytest tests/test_x.py::test_y -q`
- 前端类型检查必须用 `npm run typecheck`（先 `next typegen` 再 `tsc --noEmit`）；直接 `tsc` 会因缺全局生成类型报 `TS2304`。
- 验证顺序：`make lint` → `cd frontend && npm run typecheck` → `make test`。

## 关键约束与陷阱

- **PG 集成测试会静默 skip**：`test_db_event_store`、`test_migrations`、`test_full_flow`、`test_api_sessions` 等在 PostgreSQL 不可用时 `pytest.skip`，全绿不代表跑过。验证前先 `make db-up && make migrate`。
- **LLM key 与测试策略（ADR-0003 / #28）**：生产生成链路已切换 LangGraph workflow，**直连真实 LLM，不再有确定性兜底路径参与生产**。测试分两类：契约/纯逻辑测试无 key 全绿（workflow 测试用按 purpose 路由的 scripted LLM，仅测试用）；真实 LLM 链路测试与冒烟 key-gated（无 key `pytest.skip`，完整冒烟 `cd backend && uv run python -m scripts.smoke_workflow`）。旧确定性合成/fake 路径仅作为测试脚手架保留，随 #33 退役。`backend/app/agents/fake_llm.py` 只服务运行时 Stage2/3 链路。
- **契约单源四处**：`backend/app/contracts/`（Pydantic）→ `contracts/fixtures/` → `contracts/jsonschema/` → `frontend/src/lib/contracts/types.ts`。改契约后跑 `cd backend && uv run python -m scripts.export_contracts`；`tests/test_contracts.py` 会断言导出与 fixtures 不过期。流程见 `docs/contract-change-process.md`。
- **后端必须单 worker**：会话运行时与 WS outbox 保存在进程内存，多 worker/多副本需共享运行时 + 粘性会话。
- **账号基线破坏式重建**（ADR-0002 / #17）：旧匿名库不兼容，跑测试前先 `make db-reset`；匿名 `POST /api/sessions` 已移除，新入口由 #21 提供。鉴权代码在 `backend/app/auth/`。
- 前端是 Next.js 16，API/约定可能与训练数据不同：写代码前读 `frontend/AGENTS.md` 指向的 `node_modules/next/dist/docs/`。
- commit 用 Conventional Commits 前缀（`feat`/`fix`/`docs`…），描述、注释、文档用中文。

## 依赖与包管理器

前端统一 **npm**，以 `frontend/package-lock.json` 为准：CI、`frontend/Dockerfile`、`scripts/dev.sh` 均用 `npm ci` / `npm run`。本地若用 bun，`bun.lock` 已被 gitignore，不要提交；提交依赖变更前用 `npm ci` 验证，避免与 CI/Docker 解析出不同版本。

后端统一 **uv**，以 `backend/uv.lock` 为准。

## Agent skills

- Issue tracker：GitHub Issues，用 `gh` CLI。见 `docs/agents/issue-tracker.md`。
- Triage labels：`needs-triage` / `needs-info` / `ready-for-agent` / `ready-for-human` / `wontfix`。见 `docs/agents/triage-labels.md`。
- Domain docs：单上下文布局，`CONTEXT.md` 在仓库根、ADR 在 `docs/adr/`。见 `docs/agents/domain.md`。

### 回复语言

回复用户时的最终总结部分请使用中文。
