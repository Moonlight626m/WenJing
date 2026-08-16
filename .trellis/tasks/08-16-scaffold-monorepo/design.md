# 骨架搭建技术设计

## 架构边界

```
Wenjing/
├── backend/                 # FastAPI 单进程 asyncio
│   ├── app/
│   │   ├── main.py          # FastAPI app 工厂 + REST/WS 路由注册
│   │   ├── config.py        # pydantic-settings 配置（env）
│   │   ├── api/             # REST 路由（sessions/health）+ websocket
│   │   ├── core/            # Game Engine 占位 / LLM Service 占位 / event store 占位
│   │   ├── agents/          # screenwriter/verifier/character 占位（LangChain/LangGraph）
│   │   ├── db/              # SQLAlchemy async + Alembic + models 占位
│   │   └── schemas/         # Pydantic 消息协议类型（design_02 骨架）
│   ├── pyproject.toml       # uv 管理
│   ├── alembic/             # 迁移
│   └── tests/               # pytest 骨架
├── frontend/                # Next.js (create-next-app) + zustand + Tailwind
│   ├── app/                 # 首页 + game 占位页
│   ├── components/          # narrative/interaction/layout/phase 占位
│   ├── stores/              # gameStore/wsStore/uiStore 骨架
│   ├── lib/                 # ws.ts / api.ts / types.ts
│   └── package.json
├── docker-compose.yml       # 本地 PostgreSQL
├── Makefile                 # 常用命令（dev/test/migrate）
└── README.md
```

## 关键技术决策

| 维度 | 决策 |
|------|------|
| 依赖管理 | uv + pyproject.toml（backend）；npm（frontend） |
| 配置 | pydantic-settings，`.env`（.env.example 入库） |
| DB | SQLAlchemy 2.x async + asyncpg + Alembic；本地 docker-compose 起 PG |
| WebSocket | FastAPI WebSocket 端点 + `react-use-websocket`（前端封装） |
| 前端生成 | create-next-app（TS + Tailwind + App Router） |

## 数据流 / 契约（骨架阶段）

- `GET /health` → `{"status": "ok"}`（不含 DB 依赖，可选 `?check_db=true`）
- `POST /api/sessions` → 返回 session_id 占位
- `WS /ws?session_id=xxx` → 占位回声/连接确认
- 消息协议类型按 design_02 建 Pydantic/TS 骨架（不实现逻辑）

## 兼容性 / 迁移

- 骨架不引入业务逻辑，后续每个功能模块（引擎/Agent/持久化/前端交互）独立建任务填充。
- 目录结构对齐 design_04/design_05 文档。

## 权衡

- docker-compose 仅本地开发用；云服务器部署编排为后续任务。
- 骨架阶段 ws 只做连接/回声，验证链路通即可。
