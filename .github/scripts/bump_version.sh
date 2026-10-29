#!/usr/bin/env bash
# push dev 时按本次 push 的实际改动决定是否 bump 版本号。
# 用法：bump_version.sh <github.event.before>；stdout 只输出 bumped=...（喂 GITHUB_OUTPUT）。
set -euo pipefail

BEFORE="${1:-}"
BACKEND_DIR="backend"
FRONTEND_DIR="frontend"

HEAD_SHA="$(git rev-parse HEAD)"

changed() {
    # BEFORE 为全零（新分支/首个 commit）或对象不在历史里时，退化为与 HEAD~1 比；
    # 正常路径用 event.before——上一个 dev tip，配合 checkout fetch-depth:0 全覆盖整次 push。
    local base
    if [[ "$BEFORE" =~ ^0+$ ]] || ! git cat-file -e "$BEFORE" 2>/dev/null; then
        base="HEAD~1"
    else
        base="$BEFORE"
    fi
    # 命令替换判空而非 grep -q：后者在大 diff 下早退触发 SIGPIPE，pipefail 下误判无改动
    [[ -n "$(git diff --name-only "$base" "$HEAD_SHA" -- "$1" 2>/dev/null)" ]]
}

bumped_backend=false
bumped_frontend=false

# backend 应用代码改动 → patch bump pyproject.toml（uv version 同步 uv.lock）。
# uv.lock / pyproject 自身的改动是上次 bump 或手工锁更新的产物，不再触发。
# bump 工具输出压到 stderr：本脚本 stdout 全量进 GITHUB_OUTPUT，只允许 name=value。
if changed "backend/app" || changed "backend/alembic" || changed "backend/tests" || changed "backend/scripts"; then
    (cd "$BACKEND_DIR" && uv version --bump patch >&2)
    bumped_backend=true
fi

# frontend 应用代码改动 → patch bump package.json（npm version 同步 package-lock.json）
if changed "frontend/src" || changed "frontend/tests" || changed "frontend/public"; then
    (cd "$FRONTEND_DIR" && npm version patch --no-git-tag-version >&2)
    bumped_frontend=true
fi

# 契约文件有改动时提醒手动定级（不自动动 CONTRACTS_SCHEMA_VERSION：
# minor/breaking 要按 docs/contract-change-process.md 评审决定）。
# 注意打 stderr：脚本 stdout 全量进 GITHUB_OUTPUT，hint/提示走 stderr 才能进工作流日志。
if changed "backend/app/contracts" || changed "contracts" || changed "frontend/src/lib/contracts"; then
    echo "::notice::共享契约文件有改动——CONTRACTS_SCHEMA_VERSION 需按 docs/contract-change-process.md 评审后手动递增" >&2
fi

if [[ "$bumped_backend" == true || "$bumped_frontend" == true ]]; then
    echo "bumped=true"
else
    echo "bumped=false"
fi
