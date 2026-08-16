# 文境 (Wenjing)

面向学生的语文课文情景演绎 multi-agent 角色扮演平台。基于课文由编剧 Agent 生成剧本，玩家与角色 Agents 共同演绎剧情，还原课文后进入同人续写。

> 功能设计与技术决议见 [`design/`](design/design.md) 与 `.trellis/`（Trellis 管理）。

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

## 快速开始

### 1. 安装依赖

```bash
make install
```

### 2. 启动本地数据库（PostgreSQL）

```bash
make db-up
cp backend/.env.example backend/.env   # 按需修改
make migrate
```

### 3. 启动服务

```bash
make dev-backend    # http://localhost:8000
make dev-frontend   # http://localhost:3000
```

验证：`curl http://localhost:8000/health` → `{"status":"ok"}`

## 常用命令

| 命令 | 作用 |
|------|------|
| `make test` | backend pytest |
| `make lint` | backend ruff + frontend eslint |
| `make build` | frontend 生产构建 |
| `make db-down` | 停止本地 PG |

## 当前状态

骨架搭建阶段（scaffold）：仅基础框架与占位端点，业务逻辑（游戏引擎 / Agent 编排 / 消息协议实现）逐步以 Trellis 任务填充。
