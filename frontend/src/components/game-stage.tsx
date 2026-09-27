"use client";

import type { ReactNode } from "react";

/**
 * 游玩页舞台（ADR-0005 §1，issue #52 M3-1）：全屏背景铺底 + 场景切换淡入 + 场景标题。
 *
 * 背景 URL / 场景 key 由 M3-2（#53）经 `current_asset`/`scene_key` 投影接入；
 * 本里程碑先提供 UI 原语，未接线时降级为暗色渐变（无图纯文本可用）。
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
  return (
    <div className="relative flex min-h-0 flex-1 flex-col overflow-hidden bg-zinc-950">
      <div
        aria-hidden
        data-testid="stage-background"
        key={backgroundUrl ?? "gradient"}
        className={`absolute inset-0 z-0 ${
          backgroundUrl
            ? "animate-stage-fade bg-cover bg-center"
            : "bg-gradient-to-b from-zinc-800 via-zinc-900 to-black"
        }`}
        style={
          backgroundUrl ? { backgroundImage: `url(${backgroundUrl})` } : undefined
        }
      />
      {sceneTitle && (
        <div
          key={sceneKey ?? sceneTitle}
          data-testid="scene-title"
          className="animate-scene-title pointer-events-none absolute inset-x-0 top-8 z-20 flex justify-center"
        >
          <span className="rounded bg-black/45 px-5 py-2 text-xl font-medium text-white/95 [text-shadow:0_1px_4px_rgba(0,0,0,0.9)] md:text-2xl">
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
