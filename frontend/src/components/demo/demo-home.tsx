"use client";

import { Suspense, useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AnimatePresence, m } from "motion/react";

import { SHELF } from "@/lib/demo/catalog";
import { clearUnlocked } from "@/lib/demo/store";
import { useEffectsLevel, useUiStore } from "@/stores/uiStore";
import { ScrollShelf } from "@/components/demo/scroll-shelf";
import { TitleScroll } from "@/components/demo/title-scroll";
import { StageParticles } from "@/components/stage-particles";
import { MotionRoot } from "@/components/ui/motion-root";

/** 开卷 → 书匣。从演出页「回到书匣」回来时带 `?shelf=1`，直接停在书匣。 */
export function DemoHome() {
  return (
    <Suspense fallback={<main data-surface="stage" className="min-h-screen bg-canvas" />}>
      <DemoHomeContent />
    </Suspense>
  );
}

function DemoHomeContent() {
  const searchParams = useSearchParams();
  const [view, setView] = useState<"title" | "shelf">(
    searchParams.get("shelf") ? "shelf" : "title"
  );
  const full = useEffectsLevel() === "full";
  const hydrateEffects = useUiStore((s) => s.hydrateEffects);

  useEffect(() => {
    hydrateEffects();
  }, [hydrateEffects]);

  return (
    <main
      data-surface="stage"
      data-effects={full ? "full" : "lite"}
      className="relative flex min-h-screen w-full flex-col overflow-x-clip bg-canvas"
    >
      <div aria-hidden className="pointer-events-none fixed inset-0">
        <div className="stage-aurora animate-aurora absolute -inset-[12%]" />
        {full && <StageParticles />}
        <div className="stage-vignette absolute inset-0" />
      </div>

      <MotionRoot>
        <AnimatePresence mode="wait">
          <m.div
            key={view}
            initial={{ opacity: 0, filter: "blur(8px)" }}
            animate={{ opacity: 1, filter: "blur(0px)" }}
            exit={{ opacity: 0, filter: "blur(8px)", transition: { duration: 0.45 } }}
            transition={{ duration: 0.7 }}
            className="relative flex flex-1 flex-col"
          >
            {view === "title" ? (
              <TitleScroll onEnter={() => setView("shelf")} />
            ) : (
              <ScrollShelf scrolls={SHELF} />
            )}
          </m.div>
        </AnimatePresence>
      </MotionRoot>

      {view === "shelf" && (
        <footer className="relative flex justify-center gap-4 pb-5 text-2xs text-ink-faint">
          <button type="button" className="hover:text-ink-soft" onClick={() => setView("title")}>
            回到开卷
          </button>
          <button
            type="button"
            className="hover:text-ink-soft"
            onClick={() => {
              for (const s of SHELF) clearUnlocked(s.slug);
              window.location.reload();
            }}
          >
            清空结局图鉴（彩排用）
          </button>
        </footer>
      )}
    </main>
  );
}
