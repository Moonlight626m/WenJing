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
make install     # 安装 backend (uv sync) 与 frontend (npm install) 依赖
make db-up       # 启动本地 PostgreSQL (docker compose)
cp backend/.env.example backend/.env   # 配置环境变量，按需修改
make migrate     # 运行 Alembic 迁移，初始化数据库表
```

## 运行

两个终端分别启动：

```bash
make dev-backend    # backend: http://localhost:8000 (uvicorn --reload)
make dev-frontend   # frontend: http://localhost:3000 (next dev)
```

验证 backend：`curl http://localhost:8000/health` → `{"status":"ok"}`

停止数据库：`make db-down`

## 常用命令

| 命令 | 作用 |
|------|------|
| `make test` | backend pytest |
| `make lint` | backend ruff + frontend eslint |
| `make build` | frontend 生产构建 |
| `make db-down` | 停止本地 PG |

## 当前状态

骨架搭建阶段（scaffold）：仅基础框架与占位端点，业务逻辑（游戏引擎 / Agent 编排 / 消息协议实现）按 `design/` 逐步填充。
