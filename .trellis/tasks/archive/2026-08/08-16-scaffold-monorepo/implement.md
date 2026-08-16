# 骨架搭建执行计划

> 目标：搭建可启动、可验证的 monorepo 骨架，不含业务逻辑。

## 前置环境

- [ ] 0. 安装 uv：`curl -LsSf https://astral.sh/uv/install.sh | sh`（若缺）

## 有序执行清单

### backend
- [ ] 1. 创建 `backend/`，`uv init` 生成 pyproject.toml；添加依赖：fastapi, uvicorn[standard], pydantic-settings, sqlalchemy[asyncio], asyncpg, alembic, langchain, langgraph, openai, websockets
- [ ] 2. 创建 `app/` 目录结构与占位模块（config/api/core/agents/db/schemas）
- [ ] 3. `app/main.py`：FastAPI app 工厂 + `/health` + `POST /api/sessions` 占位 + `WS /ws` 占位
- [ ] 4. `app/config.py`：pydantic-settings（DATABASE_URL 等），`.env.example` 入库
- [ ] 5. db：SQLAlchemy async engine/session 依赖 + Alembic 初始化 + 首个空迁移
- [ ] 6. `tests/`：pytest + httpx 健康检查测试

### frontend
- [ ] 7. `npx create-next-app@latest frontend`（TS + App Router + Tailwind + ESLint）
- [ ] 8. 安装 zustand、react-use-websocket、react-markdown
- [ ] 9. 创建 `stores/`（gameStore/wsStore/uiStore 骨架）与 `lib/`（ws.ts/api.ts/types.ts）
- [ ] 10. 首页（课文导入占位）+ `app/game/` 占位页 + 根布局清理

### 根目录
- [ ] 11. `docker-compose.yml`（本地 PG）+ `.env.example`
- [ ] 12. `Makefile`（dev/test/migrate 命令）+ `README.md`（启动/验证说明）

## 验证命令

```bash
# backend
cd backend && uv run alembic upgrade head   # 迁移成功
cd backend && uv run pytest                 # 测试通过
cd backend && uv run uvicorn app.main:app --port 8000
curl http://localhost:8000/health           # {"status":"ok"}

# frontend
cd frontend && npm run build                # 构建成功
cd frontend && npm run dev                  # 可访问首页与 /game

# db
docker compose up -d db                     # PG 启动
```

## 风险点 / 回滚

- uv 未安装 → 先装 uv；若网络受限可退 pip。
- create-next-app 版本差异 → 按生成的实际版本调整依赖。
- LangChain/LangGraph 仅在 pyproject 声明，不写逻辑，避免骨架过大。

## 后续动作（本任务结束后）

- 任务：Game Engine 骨架 / Agent 骨架 / 数据模型 / WS 消息协议实现 / 前端消息流。
