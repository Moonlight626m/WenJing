<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## 依赖与包管理器

统一使用 **npm**，以 `package-lock.json` 为准（CI、Dockerfile、scripts/dev.sh 均如此）。本地若用 bun，`bun.lock` 已被 gitignore，不要提交；提交依赖变更前用 `npm ci` 验证。

类型检查用 `npm run typecheck`（先 `next typegen` 再 `tsc --noEmit`）：`LayoutProps` 等全局类型由 Next 生成，直接跑 `tsc` 会报 `TS2304`。
