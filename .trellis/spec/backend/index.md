# Backend Development Guidelines

> Best practices for backend development in this project.

---

## Overview

This directory contains guidelines for backend development. Fill in each file with your project's specific conventions.

---

## Tech Stack Baseline (Decided)

| Area | Decision |
|------|----------|
| Framework | FastAPI, single-process asyncio event loop |
| Agent framework | LangChain (agent internals) + LangGraph (Stage/phase state machine & sub-agent orchestration) |
| LLM | LLM Service singleton shared across agents, semaphore rate-limit, provider-switchable (OpenAI/DeepSeek/Qwen) |
| API | REST + WebSocket (no MCP in MVP; no Redis/message queue) |
| Database | PostgreSQL (JSONB for event-sourcing payloads) |
| Persistence | Event sourcing + checkpoint snapshots (every 20 events), rollback ≤100 steps |

> Full decision record (D1–D15): `.trellis/tasks/08-16-brainstorm-requirements-techstack/prd.md`
> System design: `design/design_03_game_engine.md`, `design/design_04_data_persistence.md`

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Database Guidelines](./database-guidelines.md) | ORM patterns, queries, migrations | To fill |
| [Error Handling](./error-handling.md) | Error types, handling strategies | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Logging Guidelines](./logging-guidelines.md) | Structured logging, log levels | To fill |

---

## How to Fill These Guidelines

For each guideline file:

1. Document your project's **actual conventions** (not ideals)
2. Include **code examples** from your codebase
3. List **forbidden patterns** and why
4. Add **common mistakes** your team has made

The goal is to help AI assistants and new team members understand how YOUR project works.

---

**Language**: All documentation should be written in **English**.
