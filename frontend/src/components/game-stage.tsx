"use client";

import { useEffect, useRef, type ReactNode } from "react";

import { useEffectsLevel } from "@/stores/uiStore";
import { StageParticles } from "@/components/stage-particles";

/** 题签为竖排的最大字数；更长的标题（LLM 生成的场景名不受长度约束）改横排。 */
const SLIP_MAX_CHARS = 8;

/**
 * 指针视差：把指针相对舞台中心的偏移（-0.5 ~ 0.5）写进 `--wj-px` / `--wj-py`。
 * 背景层朝反方向挪、立绘层朝同方向挪，画面就有了前后景深。只写 CSS 变量、
 * 一帧最多写一次，不触发 React 重渲染；触屏设备没有悬停指针，不启用。
 */
function useParallax(enabled: boolean) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const root = ref.current;
    if (!enabled || !root) return;
    if (!window.matchMedia("(pointer: fine)").matches) return;
    let frame = 0;
    let px = 0;
    let py = 0;
    function onMove(e: PointerEvent) {
      const rect = root!.getBoundingClientRect();
      px = (e.clientX - rect.left) / rect.width - 0.5;
      py = (e.clientY - rect.top) / rect.height - 0.5;
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        root!.style.setProperty("--wj-px", px.toFixed(3));
        root!.style.setProperty("--wj-py", py.toFixed(3));
      });
    }
    root.addEventListener("pointermove", onMove);
    return () => {
      root.removeEventListener("pointermove", onMove);
      cancelAnimationFrame(frame);
      root.style.removeProperty("--wj-px");
      root.style.removeProperty("--wj-py");
    };
  }, [enabled]);
  return ref;
}

/**
 * 游玩页舞台（ADR-0005 §1）：全屏背景铺底 + 幕启 + 场景题签。
 *
 * 暗色令牌由游玩页根节点的 `data-surface="stage"` 提供（见 app/game/page.tsx），
 * 舞台恒暗、与系统配色无关，子组件因此不必写 `dark:` 变体——旧样式正是在这里
 * 出错（硬编码暗底舞台上摆着浅色卡片）。无背景图时降级为幕布渐变，纯文本仍可玩。
 *
 * 由下往上叠：背景（推镜 + 视差）→ 极光（仅无图时）→ 光尘粒子 → 暗角 → 墨晕转场
 * → 内容 → 题签。粒子、视差、墨晕只在特效「完整」档出现。
 */
export function GameStage({
  backgroundUrl = null,
  sceneKey = null,
  sceneTitle = null,
  children,
}: {
  backgroundUrl?: string | null;
  sceneKey?: string | null;
  sceneTitle?: string | null;
  children: ReactNode;
}) {
  const full = useEffectsLevel() === "full";
  const rootRef = useParallax(full);
  const vertical = sceneTitle !== null && sceneTitle.length <= SLIP_MAX_CHARS;

  return (
    <div
      ref={rootRef}
      // clip 而不是 hidden：视差层、极光层都比舞台大一圈，hidden 的容器仍可被程序滚动，
      // 焦点一变（如换交互卡）浏览器就把整块舞台往上滚，顶栏被挤出视野
      className="relative flex min-h-0 flex-1 flex-col overflow-clip bg-canvas"
    >
      {/* 视差层比舞台外扩一圈，挪动时四边不露底 */}
      <div
        aria-hidden
        className="absolute -inset-[3%] z-0 transition-transform duration-700 ease-out"
        style={{
          transform:
            "translate3d(calc(var(--wj-px, 0) * -22px), calc(var(--wj-py, 0) * -14px), 0)",
        }}
      >
        <div
          data-testid="stage-background"
          key={backgroundUrl ?? "gradient"}
          className={`absolute inset-0 ${
            backgroundUrl
              ? "animate-stage-kenburns bg-cover bg-center"
              : "bg-[radial-gradient(125%_85%_at_50%_0%,var(--wj-surface)_0%,var(--wj-canvas)_58%,var(--wj-sunken)_100%)]"
          }`}
          style={
            backgroundUrl ? { backgroundImage: `url(${backgroundUrl})` } : undefined
          }
        />
        {/* 无图时幕布上漂着一层极光；比四边外扩一圈，漂移时不露出硬边 */}
        {!backgroundUrl && (
          <div className="stage-aurora animate-aurora pointer-events-none absolute -inset-[12%]" />
        )}
      </div>
      {full && <StageParticles />}
      <div aria-hidden className="stage-vignette pointer-events-none absolute inset-0 z-0" />

      {/* 墨晕：每换一幕重挂一次，墨色从画面中心化开。只盖背景，不盖界面 */}
      {full && sceneKey && (
        <div
          key={`ink:${sceneKey}`}
          aria-hidden
          className="stage-ink animate-ink-open pointer-events-none absolute inset-0 z-[5]"
        />
      )}

      {sceneTitle && (
        <div
          key={sceneKey ?? sceneTitle}
          data-testid="scene-title"
          className={
            vertical
              ? "animate-slip-brush-v pointer-events-none absolute top-20 right-4 z-20 md:right-7"
              : "animate-slip-brush-h pointer-events-none absolute inset-x-0 top-20 z-20 flex justify-center px-6"
          }
        >
          <span
            className={[
              "font-serif text-ink [text-shadow:0_0_18px_color-mix(in_srgb,var(--wj-glow-gold)_55%,transparent),0_1px_6px_rgba(0,0,0,0.85)]",
              "border border-glow-gold/40 bg-panel shadow-[0_0_30px_-10px_var(--wj-glow-gold)] backdrop-blur-[2px]",
              vertical
                ? "title-slip rounded-sm px-2.5 py-4 text-xl tracking-[0.3em] md:text-2xl"
                : "inline-block rounded-sm px-4 py-2 text-lg tracking-[0.2em] md:text-xl",
            ].join(" ")}
          >
            {sceneTitle}
          </span>
        </div>
      )}

      <div className="relative z-10 flex min-h-0 flex-1 flex-col">
        {children}
      </div>
    </div>
  );
}
