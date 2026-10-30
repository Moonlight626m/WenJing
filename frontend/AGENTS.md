<!-- BEGIN:nextjs-agent-rules -->

# This is NOT the Next.js you know

This version has breaking changes — APIs, conventions, and file structure may all differ from your training data. Read the relevant guide in `node_modules/next/dist/docs/` (resolved from this file's directory; in monorepos the `next` package may not be visible from the repo root) before writing any code. Heed deprecation notices.

This block is written and re-added by `next dev` — verify at `node_modules/next/dist/server/lib/generate-agent-files.js`. Removing it from a diff only re-creates the uncommitted change; committing it with your work keeps the tree clean.

<!-- END:nextjs-agent-rules -->

## 依赖与包管理器

统一使用 **npm**，以 `package-lock.json` 为准（CI、Dockerfile、scripts/dev.sh 均如此）。本地若用 bun，`bun.lock` 已被 gitignore，不要提交；提交依赖变更前用 `npm ci` 验证。

类型检查用 `npm run typecheck`（先 `next typegen` 再 `tsc --noEmit`）：`LayoutProps` 等全局类型由 Next 生成，直接跑 `tsc` 会报 `TS2304`。

## 样式系统

语义令牌在 `src/app/globals.css`（`--wj-*` 定义，经 Tailwind v4 `@theme inline` 暴露成
`bg-surface` / `text-ink` / `border-rule` 这类工具类），共享原语在 `src/components/ui/`。
**改样式只动这两处与调用点，不要在组件里写调色板类。**

### 两个面

产品有两副"面"，共用同一套语义令牌，由祖先元素的 `data-surface` 决定：

| 面 | 谁在用 | 底色 |
|----|--------|------|
| 册（纸面） | 登录/注册、学生空间、教师工作台、运营后台 | 亮色，随系统配色切到"夜读"暗色 |
| 台（幕布） | 仅游玩页 `/game` | **恒暗**，与系统配色无关（`<main data-surface="stage">`） |

四条容易踩的：

- **不要写 `dark:` 变体。** 令牌会随所在面自动解析。舞台恒暗而子组件按系统配色取色，
  正是改造前的老 bug（暗幕布上摆着 `bg-blue-50` 的卡片，浅色系统下必然糊）。
- **游玩页的暗色来自根节点的 `data-surface="stage"`**，不是 `GameStage` 组件自己带的。
  Toast 等渲染在 `GameStage` 之外的节点也要吃到舞台色，所以作用域挂在 `<main>` 上。
- **没有 twMerge。** `className` 是纯字符串拼接，两个同类工具类（`w-full` 与 `w-52`、
  `py-2` 与 `py-1`）会同时生效，胜负取决于生成顺序。所以原语**不许把可覆盖的属性写进基类**
  ——宽度、内边距一律由调用方给或走 prop（见 `ui/field.tsx` 的 `controlSize`）。
- **朱砂（`flag`）只标"在场"**：你演的角色、正在推进、流式光标、录音中。它是语义色不是装饰色，
  别拿去标"错误"（用 `danger`）或"成功"（用 `ok`）。

### 字体

不引 webfont（CJK 字体包 10MB+）。界面用系统黑体，正文与标题用系统宋体——课文在课本里
本就是宋体排的。衬线栈按「质量优先 → 平台自带 → Linux 兜底」排列，**Linux 上若漏掉
`AR PL UMing CN` 这类名字，整个衬线层会静默退化成黑体**（开发机与 CI 常见）。

### 可访问性

令牌的对比度已按 WCAG AA 逐个校验（`ink-faint` 曾因图片占位文案落在 `bg-sunken` 上而不达标，
已调深）。**改任何颜色令牌后要重新校验**：正文/meta 文字对 `canvas`/`surface`/`sunken` 三种底
都要 ≥ 4.5:1。键盘焦点由 `globals.css` 的基础层统一给（`:focus-visible`），新组件不必各写一遍。

### 界面总览 `/showcase`

`/showcase` 是**纯前端画廊**：真实组件 + `components/showcase/fixtures.ts` 里的假数据，
不登录、不碰后端。改版式或配色后先开它看一眼，比走 seed → 登录 → 点进去快得多。

三条它自己的约定：

- **假数据只放在 `fixtures.ts`**。资产槽位故意不给 `status: "ready"`——`useAssetUrl` 见到
  ready 就会去签预签名 URL，画廊不登录、后端也不该被它碰到（那会是一串 401）。
- 画廊**不渲染真正的页面组件**（`app/student/page.tsx` 等），因为那些页面自己拉接口。
  它只搭内容层，并复用已导出的 `GameRow` / `SquareCard` / `ScriptCard`，不另抄一份。
- 舞台那一屏的骨架与 `app/game/page.tsx` **有意重复**（把游戏页版式抽成共享组件会动到
  WS / 状态机接线，为一个画廊页不值得）。**改游戏页版式时记得同步这一屏。**

### 端到端测试（Playwright）

`make e2e` = `cd frontend && npm run test:e2e`（全量）。前置：后端 :8000 已 `make seed`、
前端 :3000；想跑快就 `WENJING_LLM_API_KEY= ./scripts/dev.sh restart` 走确定性 fake（秒级）。

**断言标题文字要用 `getByRole("heading", ...)`，不要用裸 `getByText`。** Next.js App Router
在客户端导航后会往 `#__next-route-announcer__` 里写一份新页面的 `<h1>` 文本（读屏播报用），
于是裸文本查询会同时命中标题和那个 live region，撞 strict mode 报
`resolved to 2 elements`。这个坑会随页面变快而**从偶发转成必现**——页面本身没坏，是断言
不够精确。

跑单个文件要传**路径**（`npx playwright test tests/e2e/core-flow.spec.ts`）；传裸文件名会被
当成正则过滤器，加载报 `did not expect test() to be called here`。

