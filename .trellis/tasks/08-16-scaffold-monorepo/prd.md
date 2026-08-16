# 前后端项目骨架搭建

## Goal

搭建文境 monorepo：`backend/`（FastAPI + LangChain/LangGraph + SQLAlchemy/Alembic + PostgreSQL）与 `frontend/`（Next.js + TypeScript + zustand）的空项目骨架、目录结构、基础配置与健康检查，不包含业务逻辑。

## Background（已确认事实）

- 技术栈决议（D1–D15）已收敛，见 `design/design.md` §7 与 `.trellis/tasks/08-16-brainstorm-requirements-techstack/prd.md`。
- 后端：FastAPI 单进程 asyncio；LangGraph 管状态机、LangChain 管 Agent 内部；REST+WebSocket；PostgreSQL（JSONB）；事件溯源+checkpoint。
- 前端：Next.js(App Router)+TS；zustand（gameStore/wsStore/uiStore）；react-use-websocket；Tailwind。
- 设计参考：`design/design_03_game_engine.md`（引擎）、`design_04_data_persistence.md`（持久化）、`design_05_frontend_architecture.md`（前端）、`design_02_interaction_system.md`（消息协议）。
- 用户已有云服务器，将部署前后端与 DB infra；本任务只搭骨架，不含 Docker/CI 编排（可作为后续项）。

## Requirements（收敛中）

- R1 monorepo 布局：根目录含 `backend/`、`frontend/` 两子项目，各自独立配置。
- R2 backend 骨架：FastAPI app 工厂、基础配置（env/config）、目录结构（agents/core/services/api/db）、SQLAlchemy async + Alembic 初始化、PostgreSQL 连接、REST + WebSocket 基础端点、健康检查。
- R3 frontend 骨架：Next.js App Router 项目、目录结构（components/stores/lib）、zustand 基础 store、WS client 封装、类型定义、Tailwind、首页 + 游戏页占位。
- R4 根目录：README、`make`/脚本或统一命令文档、基础 git 配置。

## Acceptance Criteria

- [ ] A1 monorepo 根目录含 `backend/` 与 `frontend/`，结构清晰可扩展
- [ ] A2 backend 可启动，`/health` 返回 OK，DB 连接可配置，Alembic 迁移初始化成功
- [ ] A3 frontend 可启动，首页与游戏占位页可访问，zustand store 与 WS client 骨架就绪
- [ ] A4 根目录 README 记录启动/验证命令
- [ ] A5 无业务逻辑（剧情/Agent 编排/消息协议实现不在本任务范围）

## Notes

- 本任务为骨架搭建（scaffold），后续业务功能各自建任务。
- Docker/CI/部署编排不在本任务范围。
