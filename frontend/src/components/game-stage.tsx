"use client";

import type { ReactNode } from "react";

/** 题签为竖排的最大字数；更长的标题（LLM 生成的场景名不受长度约束）改横排。 */
const SLIP_MAX_CHARS = 8;

/**
 * 游玩页舞台（ADR-0005 §1）：全屏背景铺底 + 幕启 + 场景题签。
 *
 * 暗色令牌由游玩页根节点的 `data-surface="stage"` 提供（见 app/game/page.tsx），
 * 舞台恒暗、与系统配色无关，子组件因此不必写 `dark:` 变体——旧样式正是在这里
 * 出错（硬编码暗底舞台上摆着浅色卡片）。无背景图时降级为幕布渐变，纯文本仍可玩。
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
  const vertical = sceneTitle !== null && sceneTitle.length <= SLIP_MAX_CHARS;

  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-canvas">
      <div
        aria-hidden
        data-testid="stage-background"
        key={backgroundUrl ?? "gradient"}
        className={`absolute inset-0 z-0 ${
          backgroundUrl
            ? "animate-stage-fade bg-cover bg-center"
            : "bg-[radial-gradient(125%_85%_at_50%_0%,var(--wj-surface)_0%,var(--wj-canvas)_58%,var(--wj-sunken)_100%)]"
        }`}
        style={
          backgroundUrl ? { backgroundImage: `url(${backgroundUrl})` } : undefined
        }
      />
      <div aria-hidden className="stage-vignette pointer-events-none absolute inset-0 z-0" />

      {sceneTitle && (
        <div
          key={sceneKey ?? sceneTitle}
          data-testid="scene-title"
          className={
            vertical
              ? "animate-slip-in pointer-events-none absolute top-20 right-4 z-20 md:right-7"
              : "animate-slip-in pointer-events-none absolute inset-x-0 top-20 z-20 flex justify-center px-6"
          }
        >
          <span
            className={[
              "font-serif text-ink [text-shadow:0_1px_6px_rgba(0,0,0,0.85)]",
              vertical
                ? "title-slip rounded-sm border border-rule bg-panel px-2.5 py-4 text-xl tracking-[0.3em] backdrop-blur-[2px] md:text-2xl"
                : "inline-block rounded-sm border border-rule bg-panel px-4 py-2 text-lg tracking-[0.2em] backdrop-blur-[2px] md:text-xl",
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
