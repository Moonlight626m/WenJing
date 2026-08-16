# Frontend Development Guidelines

> Best practices for frontend development in this project.

---

## Overview

This directory contains guidelines for frontend development. Fill in each file with your project's specific conventions.

---

## Tech Stack Baseline (Decided)

| Area | Decision |
|------|----------|
| Framework | Next.js (App Router) + TypeScript |
| State | Zustand (gameStore / wsStore / uiStore) |
| WebSocket | react-use-websocket (auto-reconnect, exponential backoff) |
| Markdown | react-markdown (narrative rendering) |
| Animation | Framer Motion + CSS transitions |
| Styling | Tailwind CSS |

> Full decision record (D1–D15): `.trellis/tasks/08-16-brainstorm-requirements-techstack/prd.md`
> System design: `design/design_02_interaction_system.md`, `design/design_05_frontend_architecture.md`

---

## Guidelines Index

| Guide | Description | Status |
|-------|-------------|--------|
| [Directory Structure](./directory-structure.md) | Module organization and file layout | To fill |
| [Component Guidelines](./component-guidelines.md) | Component patterns, props, composition | To fill |
| [Hook Guidelines](./hook-guidelines.md) | Custom hooks, data fetching patterns | To fill |
| [State Management](./state-management.md) | Local state, global state, server state | To fill |
| [Quality Guidelines](./quality-guidelines.md) | Code standards, forbidden patterns | To fill |
| [Type Safety](./type-safety.md) | Type patterns, validation | To fill |

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
