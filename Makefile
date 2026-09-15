PY := uv run
BACKEND := backend
FRONTEND := frontend

.PHONY: help install db-up db-down dev dev-stop dev-status dev-backend dev-frontend test lint build \
	build-backend build-frontend up down logs migrate demo e2e

help:
	@echo "文境 (Wenjing) 常用命令："
	@echo "  make install        安装 backend (uv) 与 frontend (npm) 依赖"
	@echo "  make db-up          启动本地 PostgreSQL (docker compose)"
	@echo "  make db-down        停止本地 PostgreSQL"
	@echo "  make migrate        运行 Alembic 迁移 (backend)"
	@echo "  make dev            一键启动 db+backend+frontend（后台，日志 .run/logs）"
	@echo "  make dev-stop       停止 make dev 启动的服务"
	@echo "  make dev-status     查看本地服务状态"
	@echo "  make dev-backend    启动 backend (uvicorn :8000，前台)"
	@echo "  make dev-frontend   启动 frontend (next dev，前台)"
	@echo "  make test           运行 backend 测试"
	@echo "  make lint           backend ruff + frontend eslint"
	@echo "  make build          frontend 生产构建"
	@echo "  make build-backend  构建 backend 生产镜像"
	@echo "  make build-frontend 构建 frontend 生产镜像"
	@echo "  make up             启动完整生产栈 (db+backend+frontend+nginx)"
	@echo "  make down           停止完整生产栈"
	@echo "  make logs           查看生产栈日志"
	@echo "  make e2e            浏览器端到端测试 (Playwright)"
	@echo "  make demo           端到端流程演示（需 backend 运行在 :8000）"

install:
	cd $(BACKEND) && uv sync
	cd $(FRONTEND) && npm install

db-up:
	docker compose up -d db

db-down:
	docker compose down

migrate:
	cd $(BACKEND) && $(PY) alembic upgrade head

dev:
	./scripts/dev.sh start

dev-stop:
	./scripts/dev.sh stop

dev-status:
	./scripts/dev.sh status

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

build-backend:
	docker compose build backend

build-frontend:
	docker compose build frontend

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

e2e:
	cd $(FRONTEND) && npm run test:e2e

demo:
	cd $(BACKEND) && $(PY) python scripts/demo_flow.py
