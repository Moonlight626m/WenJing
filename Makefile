PY := uv run
BACKEND := backend
FRONTEND := frontend

.PHONY: help install db-up db-down dev-backend dev-frontend test lint build migrate

help:
	@echo "文境 (Wenjing) 常用命令："
	@echo "  make install        安装 backend (uv) 与 frontend (npm) 依赖"
	@echo "  make db-up          启动本地 PostgreSQL (docker compose)"
	@echo "  make db-down        停止本地 PostgreSQL"
	@echo "  make migrate        运行 Alembic 迁移 (backend)"
	@echo "  make dev-backend    启动 backend (uvicorn :8000)"
	@echo "  make dev-frontend   启动 frontend (next dev)"
	@echo "  make test           运行 backend 测试"
	@echo "  make lint           backend ruff + frontend eslint"
	@echo "  make build          frontend 生产构建"

install:
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm install

db-up:
	docker compose up -d db

db-down:
	docker compose down

migrate:
	cd $(BACKEND) && $(PY) alembic upgrade head

dev-backend:
	cd $(BACKEND) && $(PY) uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

dev-frontend:
	cd $(FRONTEND) && npm run dev

test:
	cd $(BACKEND) && $(PY) pytest

lint:
	cd $(BACKEND) && $(PY) ruff check app tests
	cd $(FRONTEND) && npm run lint

build:
	cd $(FRONTEND) && npm run build
