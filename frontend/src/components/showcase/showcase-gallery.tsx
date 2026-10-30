"use client";

/**
 * /showcase 界面总览：纯前端画廊，不碰后端、不需要登录。
 *
 * 每一屏都用**真实组件**渲染，只把数据换成 `./fixtures` 里的假数据。为此有三处
 * 刻意的取舍，改这个文件前先读：
 *
 * 1. 不渲染真正的页面（`app/student/page.tsx` 等），因为那些页面自己会拉接口。
 *    这里只搭它们的内容层：`AppHeader` + 本文件的留白容器 + 真实的行/卡组件
 *    （`GameRow`/`SquareCard`/`ScriptCard` 已导出复用，不另抄一份）。
 * 2. 不用 `PageShell`/`AuthShell`——它们渲染 `<main>`，一个文档里塞十几个 `<main>`
 *    是无障碍上的硬伤。画廊自己只留一个 `<main>`，书封那屏把版式内联出来。
 * 3. 舞台那屏直接渲染 `GameScreen`，与游戏页是同一份版式。`GameScreen` 只读
 *    gameStore、不碰 WS；接 WS、拉状态都留在 `app/game/page.tsx`，所以这里往 store
 *    灌假数据（`useStageFixture`）就能原样摆出来，改版式不必回来同步。
 */

import { useEffect, useState, type ReactNode } from "react";

import { AppHeader } from "@/components/auth/app-header";
import { EndingPanel } from "@/components/ending-card";
import { GameHud } from "@/components/game-hud";
import { GameScreen } from "@/components/game-screen";
import { GoalTracker } from "@/components/goal-tracker";
import { RoleCard } from "@/components/role-card";
import { GameStage } from "@/components/game-stage";
import { Skeleton, SkeletonCard } from "@/components/skeleton";
import { GameRow, SquareCard } from "@/components/student/student-home";
import { AssetReviewSection } from "@/components/teacher/asset-review";
import { GenerationProgress } from "@/components/teacher/generation-progress";
import { GateReviewPanel } from "@/components/teacher/gate-review-panel";
import { ScriptPreview } from "@/components/teacher/script-preview";
import { ScriptCard } from "@/components/teacher/teacher-library";
import { Button } from "@/components/ui/button";
import { MotionRoot } from "@/components/ui/motion-root";
import { AuthField } from "@/components/auth/auth-field";
import { controlClass } from "@/components/ui/field";
import { Seal } from "@/components/ui/seal";
import { SectionHeading } from "@/components/ui/section";
import { Empty, Loading } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
import { scriptStatusLabel, SCRIPT_STATUS_TONES } from "@/lib/labels";
import { useGameStore } from "@/stores/gameStore";
import {
  GATE_FINAL,
  GENERATION_AWAITING,
  GENERATION_FAILED,
  GENERATION_RUNNING,
  INTERACTION,
  MESSAGES,
  MY_SCRIPTS,
  PENDING,
  SCRIPT_PACKAGE,
  SESSIONS,
  SQUARE_SCRIPTS,
  STAGE3_GOALS,
  STREAMS,
  USER_ADMIN,
  USER_STUDENT,
  USER_TEACHER,
} from "@/components/showcase/fixtures";

const SESSION_ID = SESSIONS[0].session_id;

/** 运营后台表格的示意行（真实页面从 /api/admin/usage 取）。 */
const USAGE_ROWS = [
  { purpose: "剧本生成", calls: 12, tokens: 184_320 },
  { purpose: "角色 Agent", calls: 48, tokens: 902_115 },
];

/* ── 版式骨架 ─────────────────────────────────────── */

/** 章节：序号挂在界行左侧，与剧本详情里的场景编号同一套版式语言。 */
function Chapter({
  index,
  title,
  note,
  children,
}: {
  index: number;
  title: string;
  note: string;
  children: ReactNode;
}) {
  return (
    <section className="flex gap-4">
      <span className="w-6 shrink-0 pt-1 text-right font-mono text-xs text-ink-faint tabular-nums">
        {String(index).padStart(2, "0")}
      </span>
      <div className="flex min-w-0 flex-1 flex-col gap-6 border-l border-rule pl-5">
        <div className="flex flex-col gap-1.5">
          <h2 className="text-2xl text-ink">{title}</h2>
          <p className="measure text-sm text-ink-soft">{note}</p>
        </div>
        {children}
      </div>
    </section>
  );
}

/** 一屏：标题 + 说明 + 装着真实组件的框。 */
function Specimen({
  title,
  note,
  children,
}: {
  title: string;
  note?: string;
  children: ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h3 className="text-base text-ink">{title}</h3>
        {note && <span className="text-2xs text-ink-faint">{note}</span>}
      </div>
      <div className="overflow-hidden rounded-lg border border-rule bg-canvas">
        {children}
      </div>
    </section>
  );
}

/** 模拟 AppHeader 之下的内容层留白（对应 PageShell 的间距，但不渲染 `<main>`）。 */
function PageBody({
  children,
  width = "max-w-3xl",
}: {
  children: ReactNode;
  width?: string;
}) {
  return (
    <div className={`mx-auto flex w-full flex-col gap-8 px-6 py-8 ${width}`}>
      {children}
    </div>
  );
}

/* ── 舞台：给 store 喂假数据 ───────────────────────── */

/** 游玩页的组件都直接读 zustand，所以画廊得先把 store 摆成「正在演」的样子。 */
function useStageFixture() {
  useEffect(() => {
    useGameStore.setState({
      sessionId: SESSION_ID,
      stage: "stage2_reenacting",
      playerRole: "我",
      scriptTitle: SCRIPT_PACKAGE.title,
      playableRoles: SCRIPT_PACKAGE.playable_roles,
      characters: SCRIPT_PACKAGE.characters,
      scenes: SCRIPT_PACKAGE.scenes,
      sceneKey: "scene:1",
      sceneTitle: "月下刺猹",
      messages: MESSAGES,
      streams: STREAMS,
      interaction: INTERACTION,
      allowedCommands: [
        "choose_option",
        "free_input",
        "exit_game",
        "rollback_to_event",
      ],
      pending: null,
      connection: "connected",
      audioMuted: false,
    });
    return () => {
      useGameStore.setState({
        sessionId: null,
        stage: "init",
        playerRole: null,
        characters: [],
        scenes: [],
        messages: [],
        streams: [],
        interaction: null,
        allowedCommands: [],
        pending: null,
        connection: "idle",
      });
    };
  }, []);
}

/** 题签进场只演一次就会收起；画廊让它循环重演，免得来晚的人什么都没看到。 */
function SceneTitleLoop() {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setTick((n) => n + 1), 4200);
    return () => clearInterval(timer);
  }, []);
  return (
    <div data-surface="stage" className="flex h-56 flex-col">
      <GameStage sceneKey={`loop-${tick}`} sceneTitle="月下刺猹" backgroundUrl={null}>
        <div className="flex flex-1 items-end justify-center p-4">
          <span className="text-2xs text-ink-faint">
            场景切换时题签进场，约 2.8s 后收起（此处循环演示）
          </span>
        </div>
      </GameStage>
    </div>
  );
}

/* ── 画廊 ─────────────────────────────────────────── */

export function ShowcaseGallery() {
  useStageFixture();

  return (
    <div className="min-h-screen bg-canvas">
      <header className="border-b border-rule bg-surface">
        <div className="mx-auto flex max-w-5xl flex-col gap-4 px-6 py-10 sm:px-8">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <Seal />
            <span className="font-serif text-3xl tracking-[0.2em]">文境</span>
            <span className="text-sm text-ink-faint">界面总览</span>
          </div>
          <p className="max-w-[46ch] text-sm text-ink-soft">
            下面每一屏都用真实组件渲染，数据是写死的——不需要后端，也不需要登录。
          </p>
          <p className="text-xs text-ink-faint">
            深度链接 <code className="font-mono">/showcase</code>
          </p>
          <nav className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {[
              ["#paper", "册（纸面）"],
              ["#stage", "台（幕布）"],
              ["#flow", "生成与闸门"],
              ["#states", "加载与空态"],
            ].map(([href, label]) => (
              <a key={href} href={href} className="text-accent underline">
                {label}
              </a>
            ))}
          </nav>
        </div>
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-16 px-6 py-12 sm:px-8">
        {/* ── 一 · 册 ─────────────────────────────── */}
        <div id="paper" className="scroll-mt-6">
          <Chapter
            index={1}
            title="册（纸面）"
            note="亮底、克制作业面。底色随系统配色切到「夜读」，把系统调成深色再刷一次就能看到。"
          >
            <Specimen
              title="书封：登录"
              note="md 以上书名竖排，以下转为横排——不让书封挤掉表单"
            >
              <div className="flex flex-col items-center gap-10 px-6 py-12 md:flex-row md:justify-center md:gap-20">
                <div className="flex items-center gap-4 md:flex-col md:gap-8">
                  <span className="font-serif text-2xl tracking-[0.35em] md:title-slip md:text-4xl">
                    文境
                  </span>
                  <Seal />
                </div>
                <div className="flex w-full max-w-sm flex-col gap-6">
                  <div className="flex flex-col gap-1.5 border-b border-rule pb-3">
                    <h4 className="text-xl text-ink">登录文境</h4>
                    <p className="text-sm text-ink-soft">进入课文，成为其中的人</p>
                  </div>
                  {/* 只是外观：真表单会真的发请求，画廊里不接 */}
                  <div className="flex flex-col gap-4">
                    <AuthField
                      label="邮箱或手机号"
                      name="demo-identifier"
                      value=""
                      onChange={() => {}}
                    />
                    <AuthField
                      label="密码"
                      name="demo-password"
                      type="password"
                      value=""
                      onChange={() => {}}
                    />
                    <Button tone="solid" size="md">
                      登录
                    </Button>
                    <p className="text-sm text-ink-soft">
                      还没有账号？
                      <span className="ml-1 text-accent underline">注册</span>
                    </p>
                  </div>
                </div>
              </div>
            </Specimen>

            <Specimen
              title="学生空间"
              note="顶栏 + 我的游戏 + 剧本广场；搜索框在栏目标题右侧"
            >
              <AppHeader user={USER_STUDENT} />
              <PageBody>
                <h4 className="text-3xl text-ink">学生空间</h4>
                <section className="flex flex-col gap-4">
                  <SectionHeading title="我的游戏" meta={`${SESSIONS.length} 局`} />
                  <ul className="flex flex-col gap-2">
                    {SESSIONS.map((session) => (
                      <GameRow key={session.session_id} session={session} />
                    ))}
                  </ul>
                </section>
                <section className="flex flex-col gap-4">
                  <SectionHeading
                    title="剧本广场"
                    meta={`${SQUARE_SCRIPTS.length} 篇`}
                    action={
                      <input
                        type="search"
                        placeholder="搜索课文或简介"
                        aria-label="搜索剧本"
                        className={controlClass("sm", "w-52")}
                      />
                    }
                  />
                  <div className="grid gap-3 sm:grid-cols-2">
                    {SQUARE_SCRIPTS.map((script) => (
                      <SquareCard key={script.id} script={script} />
                    ))}
                  </div>
                </section>
              </PageBody>
            </Specimen>

            <Specimen
              title="教师工作台"
              note="按生命周期分三段，计数落在标题的可访问名里"
            >
              <AppHeader user={USER_TEACHER} />
              <PageBody width="max-w-4xl">
                <div className="flex flex-wrap items-center justify-between gap-4 border-b border-rule pb-3">
                  <h4 className="text-3xl text-ink">教师工作台</h4>
                  <Button tone="accent" size="sm">
                    新建剧本
                  </Button>
                </div>
                {(
                  [
                    ["draft", "待生成或待发布"],
                    ["published", "已进入学生剧本广场"],
                    ["unpublished", "已下架，存量世界可继续"],
                  ] as const
                ).map(([status, hint]) => {
                  const group = MY_SCRIPTS.filter((s) => s.status === status);
                  return (
                    <section key={status} className="flex flex-col gap-3">
                      <SectionHeading
                        title={scriptStatusLabel(status)}
                        meta={`${group.length} 篇`}
                        action={<span className="text-xs text-ink-faint">{hint}</span>}
                      />
                      {group.length === 0 ? (
                        <p className="text-xs text-ink-faint">暂无</p>
                      ) : (
                        <div className="grid gap-3 sm:grid-cols-2">
                          {group.map((script) => (
                            <ScriptCard key={script.id} script={script} />
                          ))}
                        </div>
                      )}
                    </section>
                  );
                })}
              </PageBody>
            </Specimen>

            <Specimen
              title="剧本详情（教师 / 学生共用同一份预览）"
              note="角色带署名、场景带编号与界行；关键情节标「关键」。图片位故意留成「生成中 / 生成失败」——这里没有真图，顺带演一遍缺图降级"
            >
              <AppHeader user={USER_TEACHER} />
              <PageBody width="max-w-3xl">
                <div className="flex flex-col gap-2">
                  <span className="text-sm text-accent underline">← 剧本库</span>
                  <div className="flex flex-wrap items-center gap-2.5 border-b border-rule pb-3">
                    <h4 className="text-2xl text-ink">少年闰土</h4>
                    <Tag tone={SCRIPT_STATUS_TONES.published}>已发布</Tag>
                    <Tag>本校可见</Tag>
                  </div>
                  <p className="measure text-sm text-ink-soft">
                    从《故乡》里截取的少年时光，回到那个月下刺猹的夜晚。
                  </p>
                </div>
                <ScriptPreview scriptPackage={SCRIPT_PACKAGE} />
                <section className="flex flex-col gap-4 rounded-lg border border-rule bg-surface p-4">
                  <h5 className="border-b border-rule pb-2 text-sm text-ink-soft">操作</h5>
                  <div className="flex flex-wrap items-center gap-3">
                    <Button tone="outline" size="sm">
                      重新生成
                    </Button>
                    <Button tone="danger" size="sm">
                      删除草稿
                    </Button>
                    <label className="flex items-center gap-2 text-sm text-ink-soft">
                      <span>可见性</span>
                      <span className="w-28">
                        <select className={controlClass("sm", "w-full")} defaultValue="org">
                          <option value="org">本校可见</option>
                          <option value="public">公开</option>
                        </select>
                      </span>
                    </label>
                    <Button tone="accent" size="sm">
                      发布
                    </Button>
                  </div>
                </section>
              </PageBody>
            </Specimen>

            <Specimen
              title="运营后台"
              note="唯一一个用表格的面；数字右对齐、等宽、tabular-nums"
            >
              <AppHeader user={USER_ADMIN} />
              <PageBody width="max-w-4xl">
                <h4 className="text-3xl text-ink">运营后台</h4>
                <section className="flex flex-col gap-4">
                  <SectionHeading
                    title="剧本库"
                    meta="2 篇"
                    action={
                      <div className="flex flex-wrap gap-2">
                        <select className={controlClass("sm", "w-auto")} aria-label="组织筛选">
                          <option>全部组织</option>
                        </select>
                        <select className={controlClass("sm", "w-auto")} aria-label="状态筛选">
                          <option>全部状态</option>
                        </select>
                      </div>
                    }
                  />
                  <ul className="flex flex-col gap-2">
                    {SQUARE_SCRIPTS.map((script) => (
                      <li
                        key={script.id}
                        className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border border-rule bg-surface px-4 py-3"
                      >
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className="truncate font-serif text-base text-ink">
                              {script.name}
                            </span>
                            <Tag tone={SCRIPT_STATUS_TONES[script.status]}>
                              {scriptStatusLabel(script.status)}
                            </Tag>
                          </div>
                          <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-faint">
                            <span className="font-mono">组织 f16ca50e</span>
                            <span className="font-mono">作者 9259ae6d</span>
                          </p>
                        </div>
                      </li>
                    ))}
                  </ul>
                </section>
                <section className="flex flex-col gap-4">
                  <SectionHeading title="Token 用量" meta="2 组" />
                  <div className="overflow-x-auto rounded-lg border border-rule">
                    <table className="w-full text-left">
                      <thead className="bg-sunken">
                        <tr className="text-xs text-ink-soft">
                          <th className="px-3 py-2 font-medium">组织</th>
                          <th className="px-3 py-2 font-medium">用途</th>
                          <th className="px-3 py-2 text-right font-medium">调用次数</th>
                          <th className="px-3 py-2 text-right font-medium">总 Token</th>
                        </tr>
                      </thead>
                      <tbody>
                        {USAGE_ROWS.map((row) => (
                          <tr key={row.purpose} className="border-t border-rule text-sm">
                            <td className="px-3 py-2 font-mono text-xs">f16ca50e</td>
                            <td className="px-3 py-2">{row.purpose}</td>
                            <td className="px-3 py-2 text-right tabular-nums">
                              {row.calls}
                            </td>
                            <td className="px-3 py-2 text-right font-medium tabular-nums">
                              {row.tokens.toLocaleString()}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </section>
              </PageBody>
            </Specimen>
          </Chapter>
        </div>

        {/* ── 二 · 台 ─────────────────────────────── */}
        <div id="stage" className="scroll-mt-6">
          <Chapter
            index={2}
            title="台（幕布）"
            note="游玩页与选角页在这一面，且恒暗——与系统配色无关。朱砂专标「在场」：你演的角色、正在推进、录音中；泥金标其他角色与已走完的进度，青碧标当前与正在写出的字。"
          >
            <Specimen
              title="游玩舞台"
              note="背景图缺位时降级为极光幕布；立绘缺位时降级为竖排名牌，纯文本仍可玩"
            >
              {/* 与游玩页同一份 GameScreen，数据来自 useStageFixture 灌进 store 的假数据 */}
              <div
                data-surface="stage"
                className="relative flex h-[900px] flex-col bg-canvas"
              >
                <GameScreen />
              </div>
            </Specimen>

            <Specimen
              title="场景题签"
              note="竖排右起，随场景切换进场；标题超过 8 字改横排"
            >
              <SceneTitleLoop />
            </Specimen>

            <Specimen
              title="顶栏 · 推进中"
              note="续写阶段等待引擎：进度条停在「续写」，右侧三颗墨点依次晕开"
            >
              <div data-surface="stage" className="flex h-28 flex-col">
                <GameStage sceneKey="hud" sceneTitle={null} backgroundUrl={null}>
                  <GameHud
                    sessionId={SESSION_ID}
                    stage="stage3_extending"
                    scriptTitle={SCRIPT_PACKAGE.title}
                    playerRole="我"
                    connection="connected"
                    pending={PENDING}
                  />
                </GameStage>
              </div>
            </Specimen>

            <Specimen
              title="结局卡"
              note="阶段进入「已结束」时浮到舞台中央，「终」字朱印落下"
            >
              <div data-surface="stage" className="grid place-items-center bg-canvas px-4 py-10">
                <MotionRoot>
                  <EndingPanel
                    scriptTitle={SCRIPT_PACKAGE.title}
                    playerRole="我"
                    messages={MESSAGES}
                    goals={STAGE3_GOALS}
                    onReview={() => {}}
                  />
                </MotionRoot>
              </div>
            </Specimen>

            <Specimen
              title="续写目标"
              note="进入续写时由编剧定下，每轮判定达成；全部达成即收束。点标题可收起"
            >
              <div data-surface="stage" className="bg-canvas p-6">
                <MotionRoot>
                  <GoalTracker goals={STAGE3_GOALS} />
                </MotionRoot>
              </div>
            </Specimen>

            <Specimen
              title="选角卡"
              note="选角页同在台面上：悬停时卡片随指针倾斜、边框亮流光；选定后盖「已选」印"
            >
              <div
                data-surface="stage"
                className="grid gap-5 bg-canvas p-6 sm:grid-cols-2 lg:grid-cols-3"
              >
                <MotionRoot>
                  {SCRIPT_PACKAGE.characters.map((c) => (
                    <RoleCard
                      key={c.name}
                      profile={c}
                      playable={SCRIPT_PACKAGE.playable_roles.includes(c.name)}
                      selected={c.name === "我"}
                      submitting={false}
                      onSelect={() => {}}
                    />
                  ))}
                </MotionRoot>
              </div>
            </Specimen>
          </Chapter>
        </div>

        {/* ── 三 · 生成与闸门 ───────────────────────── */}
        <div id="flow" className="scroll-mt-6">
          <Chapter
            index={3}
            title="生成与闸门"
            note="编剧 Agent 跑到关键节点会停下来等教师审阅。节点用方章表示状态，与全站状态标记同一套语言。"
          >
            <Specimen title="生成中" note="运行中的节点用脉动方章 + 计时">
              <PageBody width="max-w-3xl">
                <GenerationProgress generation={GENERATION_RUNNING} />
              </PageBody>
            </Specimen>

            <Specimen
              title="打回与等待审阅"
              note="被打回的节点用琥珀色回环标出，考证记录默认折叠"
            >
              <PageBody width="max-w-3xl">
                <GenerationProgress generation={GENERATION_AWAITING} />
              </PageBody>
            </Specimen>

            <Specimen title="生成失败" note="失败原因走 danger 音色，不是朱砂">
              <PageBody width="max-w-3xl">
                <GenerationProgress generation={GENERATION_FAILED} />
              </PageBody>
            </Specimen>

            <Specimen
              title="终审闸门"
              note="整块用 warn 音色区分「暂停中」；配图可逐槽改，通过后才生效"
            >
              <PageBody width="max-w-3xl">
                <GateReviewPanel
                  scriptId={1}
                  review={GATE_FINAL}
                  busy={null}
                  onResume={() => {}}
                />
              </PageBody>
            </Specimen>

            <Specimen title="配图审批（闸门内的一节）" note="四操作：重新生成 / 检索替换 / 上传 / 删除">
              <PageBody width="max-w-3xl">
                <AssetReviewSection
                  scriptId={1}
                  scenes={SCRIPT_PACKAGE.scenes}
                  characters={SCRIPT_PACKAGE.characters}
                  drafts={new Map()}
                  onDraftsChange={() => {}}
                  disabled={false}
                />
              </PageBody>
            </Specimen>
          </Chapter>
        </div>

        {/* ── 四 · 状态 ───────────────────────────── */}
        <div id="states" className="scroll-mt-6">
          <Chapter
            index={4}
            title="加载与空态"
            note="加载占位与真实版式对齐，加载完成时不跳版；空态说明情况并给下一步，不渲染情绪。"
          >
            <Specimen title="加载中" note="骨架条与卡片的边距、圆角与真实内容一致">
              <PageBody width="max-w-3xl">
                <Loading />
                <Skeleton className="h-4 w-32" />
                <div className="grid gap-3 sm:grid-cols-2">
                  <SkeletonCard lines={2} />
                  <SkeletonCard lines={2} />
                </div>
              </PageBody>
            </Specimen>

            <Specimen title="空态" note="虚线边框表示「这里本来可以有东西」">
              <PageBody width="max-w-3xl">
                <Empty>还没有游戏。从下面的剧本广场挑一篇课文开始。</Empty>
                <Empty
                  action={
                    <Button tone="outline" size="sm">
                      重试
                    </Button>
                  }
                >
                  该筛选条件下暂无用量记录。
                </Empty>
              </PageBody>
            </Specimen>

            <Specimen title="状态标记（方章）" note="旧样式是圆角药丸；朱砂一格只留给「在场」">
              <PageBody width="max-w-3xl">
                <div className="flex flex-wrap items-center gap-2">
                  <Tag>草稿</Tag>
                  <Tag tone="ok">已发布</Tag>
                  <Tag tone="warn">已下架</Tag>
                  <Tag tone="accent">可扮演</Tag>
                  <Tag tone="flag">你</Tag>
                  <Tag tone="danger">生成失败</Tag>
                </div>
              </PageBody>
            </Specimen>
          </Chapter>
        </div>
      </main>

      <footer className="border-t border-rule bg-surface">
        <div className="mx-auto max-w-5xl px-6 py-8 sm:px-8">
          <p className="measure text-xs text-ink-faint">
            页面本身没有鉴权，也没有数据。要看真实数据，用 seed 账号（teacher / student /
            admin，密码 123456）从 <span className="font-mono">/login</span> 进去。
          </p>
        </div>
      </footer>
    </div>
  );
}
