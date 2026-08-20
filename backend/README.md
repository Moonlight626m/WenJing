# 文境 (Wenjing) Backend

FastAPI + LangChain/LangGraph multi-agent 服务，支撑语文课文情景演绎平台。

## 架构

```
app/
├── api/       # REST + WebSocket 路由
├── config.py  # 环境配置（Settings）
├── core/      # 游戏引擎（状态机 / 事件循环 / Agent 编排）
├── agents/    # 编剧 / 验证 / 角色 Agent + LLM Service
├── db/        # SQLAlchemy async session / 模型
└── schemas/   # 消息协议 Pydantic schema
```

> 详细设计见仓库 `design/` 目录（`design_00` 起）。

## 开发命令

```bash
uv sync                    # 安装依赖（创建 .venv）
uv run uvicorn app.main:app --reload --port 8000   # 启动
uv run pytest              # 运行测试
uv run ruff check app tests # 代码检查
```

环境变量见 `.env.example`（`make db-up` 启动 PostgreSQL 后按需配置 `.env`）。