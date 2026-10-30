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
| 台（幕布） | 游玩页 `/game`、选角页 `/roles` | **恒暗**，与系统配色无关（`<main data-surface="stage">`） |

四条容易踩的：

- **不要写 `dark:` 变体。** 令牌会随所在面自动解析。舞台恒暗而子组件按系统配色取色，
  正是改造前的老 bug（暗幕布上摆着 `bg-blue-50` 的卡片，浅色系统下必然糊）。
- **游玩页的暗色来自根节点的 `data-surface="stage"`**，不是 `GameStage` 组件自己带的。
  Toast 等渲染在 `GameStage` 之外的节点也要吃到舞台色，所以作用域挂在 `<main>` 上。
- **没有 twMerge。** `className` 是纯字符串拼接，两个同类工具类（`w-full` 与 `w-52`、
  `py-2` 与 `py-1`）会同时生效，胜负取决于生成顺序。所以原语**不许把可覆盖的属性写进基类**
  ——宽度、内边距一律由调用方给或走 prop（见 `ui/field.tsx` 的 `controlSize`）。
- **朱砂（`flag`）只标"在场"**：你演的角色、正在推进、录音中。它是语义色不是装饰色，
  别拿去标"错误"（用 `danger`）或"成功"（用 `ok`）。

### 舞台的「水墨霓虹」层

台面在宋体与朱砂之外多一层现代效果，**只在 `data-surface="stage"` 下用**，册面保持克制：

| 令牌 / 工具类 | 用途 |
|---|---|
| `glow-jade` 青碧 | 当前、正在发生：进度条当前节点、流式文字的笔尖与末尾辉光 |
| `glow-gold` 泥金 | 其他角色的名牌、已走完的进度、对白带顶端的细线 |
| `glass` / `glass-edge` | 毛玻璃浮层（顶栏、剧情回顾、抉择卡、结局卡）；圆角用 `rounded-3xl`（14px），只给这些浮层 |
| `glow-border` | 一段流光沿边框绕行，表示「轮到你了」；宿主要 `relative`，转速读 `--wj-glow-speed` |
| `choice-glow` | 抉择卡悬停 / 聚焦 / 选中时亮流光并扫一道光；宿主要 `relative overflow-hidden` |
| Button `tone="glow"` | 舞台上的主操作（发送、进入续写） |

几条约束：

- **毛玻璃不透明度别再往下调。** 背景图可能很亮，`--wj-glass` 的 0.62 是正文仍过 AA 的下限附近。
- **入场动画只填 `backwards`**（见 `.animate-rise-in`）。填 `both` 会让结束帧的 `opacity: 1`
  一直压住元素自己的样式，字幕的淡出过渡就失效了。
- **组件动效用 `motion`**（`motion/react` 的 `m.*`），子树要包在 `ui/motion-root.tsx` 的
  `MotionRoot` 里——没有它 `m.*` 会停在 `initial` 那一帧。简单的循环效果用 `globals.css`
  里的关键帧。「减少动态效果」下 CSS 循环会被压成静帧，`motion` 的位移会被关掉。

### 游玩页版式（视觉小说式）

`components/game-screen.tsx` 是整块舞台：顶栏 `GameHud` → 左列是舞台视口（`StageFigures`
立绘层 + `CastDock` 头像组 + `SubtitleTrack` 对白带）和抉择卡，右列是 `TranscriptPanel`
剧情回顾（「剧情」页 = 消息流 + 回溯栏，「原文」页 = 课文对照，「角色」页 = 人物档案）。幕间过场 `ActCurtain`、
结局卡 `EndingCard` 浮在最上层。

- **立绘按「全身立绘 → 头像 → 竖排名牌」降级**；台上最多三人，取最近开口的
  （`lib/stage-cast.ts`，纯函数）。说话人取在途流，否则看最后一条非系统消息。
- **剧情回顾在 ≥1024px 默认展开、窄屏是抽屉**。E2E 的默认视口是 1280×720，`core-flow`
  依赖消息行与回溯下拉框在首屏可见——改默认展开的断点前先看它。
- **页面上只能有一个 `<select>`**（回溯栏）：`core-flow` 用 `page.locator("select")` 定位，
  多一个就撞 strict mode。消息行里的回溯按钮可读名是「回溯到这一句」，故意避开
  `/回到 #\d+/`。
- **幕间过场全程 `pointer-events-none`**，不挡点击；每会话每幕在一个标签页里只演一次
  （sessionStorage）。
- **配音中的说话人**来自 `AudioTrackPlayer`（收到 `<audio>` 的 `playing` 才算，静音时为空），
  用 `useSpeakingSpeakers()` 订阅；只用来点亮光环，不是音量电平。
- **特效档位**：`uiStore.effects`（本机 localStorage 记住），`useEffectsLevel()` 取实际档位，
  系统「减少动态效果」时强制简洁。简洁档下粒子、视差、墨晕不渲染，CSS 循环停住，毛玻璃
  换成不模糊的实底（`[data-effects="lite"]`）。档位写在 `GameScreen` 与选角页的根节点上。
- **续写目标**（`GoalTracker`）只在续写阶段与终局出现。目标快照随 `session_init` 与三类
  系统消息（定下目标、达成目标、回溯）的 `payload.stage3_goals` 下发，store 见到就整份替换
  （`asGoals`）；回溯消息也带快照，回到续写之前会清空。
- **剧情回顾的「原文」页**只列已经演到的场景（`scene:{id}` 定位当前场景），还没演到的课文
  不提前展示；续写与终局时全部展开。`paragraph_index` 从 0 起，显示时加 1。
- **选项的 `proposed_by`** 标出「谁的主意」；系统选项（进入续写 / 到此结束）为 null。

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
- 舞台那一屏直接渲染 `GameScreen`，与游戏页同一份版式：`GameScreen` 只读 gameStore，
  接 WS、拉状态都在 `app/game/page.tsx`，画廊往 store 灌假数据即可。结局卡、选角卡另有单独样例。

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

