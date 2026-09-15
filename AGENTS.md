# Wenjing — Agent Instructions

## Agent skills

### Issue tracker

Issues live in this repo's GitHub Issues, via the `gh` CLI. See `docs/agents/issue-tracker.md`.

### Triage labels

Five canonical triage roles, each label string equal to its name (`needs-triage`, `needs-info`, `ready-for-agent`, `ready-for-human`, `wontfix`). See `docs/agents/triage-labels.md`.

### Domain docs

Single-context layout: one `CONTEXT.md` at the repo root, ADRs under `docs/adr/`. See `docs/agents/domain.md`.

系统的模块设计文档在 `design/`：探索代码或实现任何功能前，先参考该模块对应的设计文档（`design.md`、`design_00_tech_decisions.md` 及 `design_0X_*`、`design_0X_*`）；若与 ADR 冲突，以更新的 ADR 为准。

### 回复语言

回复用户时的最终总结部分请使用中文。
