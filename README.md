# 文境 (Wenjing)

面向学生的语文课文情景演绎 multi-agent 角色扮演平台。基于课文由编剧 Agent 生成剧本，玩家与角色 Agents 共同演绎剧情，还原课文后进入同人续写。

> 功能设计见 [`design/design.md`](design/design.md)；技术决议（D1–D15）见 [`design/design_00_tech_decisions.md`](design/design_00_tech_decisions.md)。

## 技术栈

| 层 | 技术 |
|----|------|
| Backend | FastAPI · LangChain + LangGraph · SQLAlchemy (async) · Alembic · PostgreSQL |
| Frontend | Next.js (App Router) · TypeScript · zustand · react-use-websocket · Tailwind |
| 通信 | REST + WebSocket (JSON) |
| 工具 | uv · docker compose · Make |

## 目录结构

```
backend/     # FastAPI 服务（app: config/api/core/agents/db/schemas）
frontend/    # Next.js 应用（app/components/stores/lib）
design/      # 系统设计文档
```

## 环境配置

### 系统依赖

| 依赖 | 版本要求 | 说明 |
|------|---------|------|
| Python | >= 3.11 | backend 运行时 |
| [uv](https://docs.astral.sh/uv/) | 最新版即可 | Python 包管理与虚拟环境 |
| Node.js | >= 20 | frontend 运行时 |
| npm | 随 Node 附带 | 前端依赖安装 |
| Docker + Docker Compose | v2 | 本地 PostgreSQL |
| Make | 任意 | 常用任务入口 |

安装 uv（已有可跳过）：

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 环境变量

backend 通过 `backend/.env` 配置（pydantic-settings，前缀 `WENJING_`）：

```bash
cp backend/.env.example backend/.env
```

| 变量 | 说明 |
|------|------|
| `WENJING_DEBUG` | 调试开关 |
| `WENJING_DATABASE_URL` | PostgreSQL 连接串（默认指向本地 docker PG） |
| `WENJING_LLM_PROVIDER` | LLM 提供方（默认 `openai`） |
| `WENJING_LLM_MODEL` | 模型名（默认 `gpt-4o-mini`） |
| `WENJING_LLM_API_KEY` | LLM API Key（调用 Agent 时必填） |
| `WENJING_LLM_BASE_URL` | 可选，兼容 OpenAI 协议的自定义端点 |

## 快速启动

```bash
make dev         # 一键：起 PostgreSQL + 跑迁移 + 起后端(:8000) + 起前端(:3000)
```

首次使用也可分步执行：

```bash
make install     # 安装 backend (uv sync) 与 frontend (npm install) 依赖
make db-up       # 启动本地 PostgreSQL (docker compose)
cp backend/.env.example backend/.env   # 配置环境变量，按需修改
make migrate     # 运行 Alembic 迁移，初始化数据库表
make seed        # 写入默认 org「文境演示学校」与 super_admin/教师/学生测试账号
```

> 账号基线为破坏式重建（ADR-0002）：旧匿名数据不再兼容。若本地库是旧 schema，
> 用 `make db-reset`（删卷 → 起库 → 迁移 → seed，**数据不可恢复**）。
> seed 账号：`admin` / `teacher` / `student`，
> 密码默认 `123456`（可用 `WENJING_SEED_PASSWORD` 覆盖）。

## 运行

一键后台启动（自动起 db、跑迁移、起后端与前端，日志在 `.run/logs/`）：

```bash
make dev            # 等价于 ./scripts/dev.sh start
make dev-status     # 查看状态
make dev-stop       # 停止
```

或两个终端分别启动（前台热更）：

```bash
make dev-backend    # backend: http://localhost:8000 (uvicorn --reload)
make dev-frontend   # frontend: http://localhost:3000 (next dev)
```

验证 backend：`curl http://localhost:8000/health` → `{"status":"ok"}`

停止数据库：`make db-down`

## 常用命令

| 命令 | 作用 |
|------|------|
| `make dev` / `make dev-stop` / `make dev-status` | 一键后台启动/停止/查看开发服务（日志在 `.run/logs/`） |
| `make db-up` / `make db-down` | 启动/停止本地 PostgreSQL (docker compose) |
| `make migrate` | 运行 Alembic 迁移 (backend) |
| `make seed` | 写入默认 org 与测试账号（幂等） |
| `make db-reset` | 破坏式重建本地库（删卷 → 迁移 → seed，数据不可恢复） |
| `make test` | backend pytest（PG 可用时含集成测试） |
| `make lint` | backend ruff + frontend eslint |
| `make build` | frontend 生产构建 |
| `make e2e` | 浏览器端到端测试（Playwright，需 backend+frontend 已运行） |
| `make demo` | 端到端流程演示（需 backend 运行在 :8000） |
| `make build-backend` / `make build-frontend` | 构建生产镜像 |
| `make up` / `make down` / `make logs` | 启动/停止/查看完整生产栈 |

其他常用验证命令：

```bash
cd backend && uv run pytest tests/test_x.py::test_y -q   # 运行单个后端测试
cd frontend && npm run typecheck                          # 前端类型检查（勿直接跑 tsc）
```

## 生产部署（Docker Compose）

单机生产栈：`db` + `backend` + `frontend` + `nginx`（同源入口，REST `/api`、WS `/ws` 反代到 backend）。

```bash
cp .env.example .env          # 至少修改 POSTGRES_PASSWORD 与 LLM 配置
docker compose up -d --build  # 构建并启动，backend 入口自动执行 Alembic 迁移
# 访问 http://<server>/ ，健康检查：http://<server>/health/ready
```

要点：

- **同源部署**：浏览器经 nginx 以相对路径 `/api`、`/ws` 访问，前端在构建期注入
  `NEXT_PUBLIC_API_BASE=""`；若前后端不同源，使用 `frontend/.env.example` 中的变量。
- **单进程约束**：会话运行时与 WS outbox 保存在进程内存中，`backend` 必须以单 worker
  运行（默认 CMD 即单 worker）。多副本/多 worker 需引入共享运行时与粘性会话。
- **生成不持久化**：Stage1 剧本生成（实测 ~100s）是进程内 asyncio 后台任务，进度只在
  内存中。**进程重启会丢失在途生成**（剧本保持 `draft`，无半成品落库）；重试路径 =
  教师在剧本详情页点击「重新生成」重跑即可，无需要人工清理的数据。
- **seed 凭据**：生产栈首次部署后需手动执行 seed（幂等），写入默认 org
  「文境演示学校」与测试账号：
  ```bash
  docker compose exec backend uv run python -m app.auth.seed
  ```
  `admin` / `teacher` / `student`，
  密码默认 `123456`（`WENJING_SEED_PASSWORD` 覆盖）。
  **生产环境必须改掉默认密码或部署后立即修改**，测试账号仅用于验证。
- **迁移**：入口脚本默认执行 `alembic upgrade head`（`WENJING_RUN_MIGRATIONS=0` 可关闭）。
- **数据库**：仅绑定 `127.0.0.1:5432`，不直接暴露公网；生产请设置强密码。
- **CI**：`.github/workflows/ci.yml` 覆盖后端 lint + PG 集成测试 + 契约测试、前端
  lint/tsc/build，以及对真实 REST/WS 的浏览器 E2E。

## 当前状态

核心 MVP 已完成（规划 #2–#13）：契约、诊断基建、持久化、GameRuntime command/step、
导入/体裁/证据、安全 RAG、Schema-first Stage1、fake-backed 竖切、真实端到端集成、
前端全流程与生产化加固。多用户化（ADR-0002 / #16）已完成（#17–#26）：账号后端、
鉴权隔离、教师创作 API、学生游玩 API、用量计量、账号/教师/学生端 UI、运营后台 UI、
文档收尾。剩余：运营后台「用户/组织」面板待后端补充端点（见 #25）。
领域术语见 [`CONTEXT.md`](CONTEXT.md)。
