"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, m } from "motion/react";

import type { StageValue } from "@/lib/contracts/types";
import { useGameStore } from "@/stores/gameStore";

/** 哪些阶段开场有幕间字幕。结局不在这里，由结局卡接手。 */
const ACTS: Partial<Record<StageValue, { act: string; title: string; note: string }>> = {
  stage2_reenacting: {
    act: "第一幕",
    title: "还原课文",
    note: "顺着课文的走向，把故事演一遍",
  },
  stage3_extending: {
    act: "第二幕",
    title: "续写新篇",
    note: "课文写到这里为止，接下来由你决定",
  },
};

/** 幕间停留时长：字写完、读一遍、再收起。 */
const HOLD_MS = 3400;

const EASE = [0.2, 0.7, 0.2, 1] as const;

function seenKey(sessionId: string, stage: StageValue): string {
  return `wj-act:${sessionId}:${stage}`;
}

/** 本标签页里这一幕是否已经演过开场。读不到存储时当没演过（多看一次无妨）。 */
function wasSeen(sessionId: string | null, stage: StageValue): boolean {
  if (!sessionId) return false;
  try {
    return window.sessionStorage.getItem(seenKey(sessionId, stage)) === "1";
  } catch {
    return false;
  }
}

function markSeen(sessionId: string | null, stage: StageValue) {
  if (!sessionId) return;
  try {
    window.sessionStorage.setItem(seenKey(sessionId, stage), "1");
  } catch {
    // 记不下来只是刷新后会再看一次开场
  }
}

/**
 * 幕间过场：进入「还原」与「续写」时，上下黑边合拢成宽银幕，中间写出幕名，
 * 约 3 秒后自己退场。每个会话每一幕在一个标签页里只演一次，刷新不重放。
 *
 * 全程 pointer-events-none：它只是看的，不挡任何操作（「跳过」按钮除外），
 * 学生可以不等它演完就直接选。
 */
export function ActCurtain() {
  const stage = useGameStore((s) => s.stage);
  const sessionId = useGameStore((s) => s.sessionId);
  const scriptTitle = useGameStore((s) => s.scriptTitle);
  const [act, setAct] = useState<StageValue | null>(null);
  // 阶段变化时在渲染期决定要不要开场（React「props 变化时调整 state」模式）
  const [lastStage, setLastStage] = useState<StageValue>(stage);
  if (stage !== lastStage) {
    setLastStage(stage);
    setAct(ACTS[stage] && !wasSeen(sessionId, stage) ? stage : null);
  }

  useEffect(() => {
    if (!act) return;
    markSeen(sessionId, act);
    const timer = setTimeout(() => setAct(null), HOLD_MS);
    return () => clearTimeout(timer);
  }, [act, sessionId]);

  const copy = act ? ACTS[act] : undefined;

  return (
    <AnimatePresence>
      {copy && (
        <m.div
          key={act}
          role="status"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
          className="pointer-events-none absolute inset-0 z-50 flex flex-col items-center justify-center bg-black/75 backdrop-blur-[2px]"
        >
          {/* 宽银幕黑边 */}
          <m.span
            aria-hidden
            initial={{ y: "-100%" }}
            animate={{ y: 0 }}
            exit={{ y: "-100%" }}
            transition={{ duration: 0.6, ease: EASE }}
            className="absolute inset-x-0 top-0 h-[13%] bg-black"
          />
          <m.span
            aria-hidden
            initial={{ y: "100%" }}
            animate={{ y: 0 }}
            exit={{ y: "100%" }}
            transition={{ duration: 0.6, ease: EASE }}
            className="absolute inset-x-0 bottom-0 h-[13%] bg-black"
          />

          <m.p
            initial={{ opacity: 0, letterSpacing: "0.2em" }}
            animate={{ opacity: 1, letterSpacing: "0.6em" }}
            transition={{ duration: 1.2, delay: 0.3, ease: EASE }}
            className="font-serif text-sm text-glow-gold"
          >
            {copy.act}
          </m.p>
          <m.h2
            initial={{ opacity: 0, clipPath: "inset(0 100% 0 0)", filter: "blur(6px)" }}
            animate={{ opacity: 1, clipPath: "inset(0 0% 0 0)", filter: "blur(0px)" }}
            transition={{ duration: 1.1, delay: 0.5, ease: EASE }}
            className="text-sheen mt-3 font-serif text-4xl tracking-[0.4em] md:text-5xl"
          >
            {copy.title}
          </m.h2>
          <m.span
            aria-hidden
            initial={{ scaleX: 0 }}
            animate={{ scaleX: 1 }}
            transition={{ duration: 0.9, delay: 0.9, ease: EASE }}
            className="mt-5 block h-px w-56 bg-linear-to-r from-transparent via-glow-gold/80 to-transparent"
          />
          <m.p
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 1.2 }}
            className="mt-4 text-center font-serif text-sm leading-relaxed text-ink-soft"
          >
            {scriptTitle && <span className="block text-ink">《{scriptTitle}》</span>}
            {copy.note}
          </m.p>

          <button
            type="button"
            onClick={() => setAct(null)}
            className="pointer-events-auto absolute top-[15%] right-6 text-xs text-ink-faint transition-colors hover:text-ink"
          >
            跳过
          </button>
        </m.div>
      )}
    </AnimatePresence>
  );
}
