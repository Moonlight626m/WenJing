"use client";

import { useCallback, useEffect, useState } from "react";

import { findScript } from "@/lib/demo/catalog";
import { DemoDirector } from "@/lib/demo/director";
import { useDemoStore } from "@/lib/demo/store";
import type { DemoScript } from "@/lib/demo/types";
import { CastSelect } from "@/components/demo/cast-select";
import { DemoEnding } from "@/components/demo/demo-ending";
import {
  FateOverlay,
  PresenterBar,
  QuoteCatch,
  SuggestionChips,
} from "@/components/demo/stage-overlays";
import { GameScreen } from "@/components/game-screen";
import { ToastHost } from "@/components/toast-host";

/**
 * 演出页：先选角，再开演。「从头再演」换一个 key 整个重来（新导演、新会话号），
 * 并跳过选角直接开场。
 */
export function DemoPlayer({ slug }: { slug: string }) {
  const script = findScript(slug);
  const [run, setRun] = useState(0);
  if (!script) return null;
  return (
    <DemoRun
      key={run}
      script={script}
      skipCast={run > 0}
      onRestart={() => setRun((r) => r + 1)}
    />
  );
}

function DemoRun({
  script,
  skipCast,
  onRestart,
}: {
  script: DemoScript;
  skipCast: boolean;
  onRestart: () => void;
}) {
  const [director] = useState(() => new DemoDirector(script));
  const [phase, setPhase] = useState<"cast" | "play">(skipCast ? "play" : "cast");
  const fate = useDemoStore((s) => s.fate);

  useEffect(() => {
    director.boot();
    return () => director.dispose();
  }, [director]);

  // 舞台挂上之后再开演：幕间过场要看到「阶段变了」才会拉幕
  useEffect(() => {
    if (phase === "play") director.begin();
  }, [phase, director]);

  const start = useCallback(() => setPhase("play"), []);

  return (
    <main
      data-surface="stage"
      data-fate={fate}
      className="flex h-screen w-full flex-col overflow-clip bg-canvas"
    >
      {phase === "cast" ? (
        <CastSelect script={script} onStart={start} />
      ) : (
        <GameScreen
          homeHref="/demo?shelf=1"
          transcriptDefault={false}
          stageOverlay={
            <>
              <FateOverlay />
              <QuoteCatch />
              <PresenterBar director={director} quoteTotal={script.quoteTotal} />
            </>
          }
          interactionAccessory={<SuggestionChips />}
          ending={(openReview) => (
            <DemoEnding
              script={script}
              director={director}
              onReview={openReview}
              onRestart={onRestart}
            />
          )}
        />
      )}
      <ToastHost />
    </main>
  );
}
