"use client";

import { useState } from "react";
import Link from "next/link";
import { AnimatePresence, m } from "motion/react";

import { earnedSeals } from "@/lib/demo/catalog";
import type { DemoDirector } from "@/lib/demo/director";
import { loadUnlocked, useDemoStore } from "@/lib/demo/store";
import type { DemoScript } from "@/lib/demo/types";
import { useGameStore } from "@/stores/gameStore";
import { Button, buttonClass } from "@/components/ui/button";
import { BranchIcon } from "@/components/ui/icons";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/** 印章在结局文字出完之后一枚一枚落下。 */
const SEAL_START_S = 1.6;
const SEAL_GAP_S = 0.32;

/**
 * 演出模式的结局：结局插画铺满舞台，竖排写出结局名，下面是这一局的成就印章、
 * 结局图鉴（解锁了几个）和平行世界的入口。替换游戏页默认的结局卡。
 */
export function DemoEnding({
  script,
  director,
  onReview,
  onRestart,
}: {
  script: DemoScript;
  director: DemoDirector;
  onReview: () => void;
  onRestart: () => void;
}) {
  const endingId = useDemoStore((s) => s.ending);
  const [dismissed, setDismissed] = useState<string | null>(null);
  // 回溯后结局清空：下一次走到结局（哪怕是同一个）要重新弹出来
  const [lastEnding, setLastEnding] = useState(endingId);
  if (endingId !== lastEnding) {
    setLastEnding(endingId);
    setDismissed(null);
  }
  const ending = script.endings.find((e) => e.id === endingId) ?? null;
  const open = ending !== null && dismissed !== endingId;

  return (
    <AnimatePresence>
      {open && ending && (
        <m.div
          key={ending.id}
          role="dialog"
          aria-modal="false"
          aria-label={`结局：${ending.title}`}
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.9 }}
          className="absolute inset-0 z-50 overflow-y-auto bg-canvas"
        >
          <div
            aria-hidden
            className="animate-stage-kenburns fixed inset-0 bg-cover bg-center"
            style={{ backgroundImage: `url(${ending.art})` }}
          />
          <div
            aria-hidden
            className="fixed inset-0 bg-linear-to-r from-black/85 via-black/55 to-black/20"
          />
          <EndingBody
            script={script}
            director={director}
            endingId={ending.id}
            onReview={() => {
              setDismissed(ending.id);
              onReview();
            }}
            onRestart={onRestart}
            onClose={() => setDismissed(ending.id)}
          />
        </m.div>
      )}
    </AnimatePresence>
  );
}

function EndingBody({
  script,
  director,
  endingId,
  onReview,
  onRestart,
  onClose,
}: {
  script: DemoScript;
  director: DemoDirector;
  endingId: string;
  onReview: () => void;
  onRestart: () => void;
  onClose: () => void;
}) {
  const flags = useDemoStore((s) => s.flags);
  const rollbacks = useDemoStore((s) => s.rollbacks);
  const quotes = useDemoStore((s) => s.quotes);
  const startedAt = useDemoStore((s) => s.startedAt);
  const canParallel = useDemoStore((s) => s.canParallel);
  const goals = useGameStore((s) => s.stage3Goals);
  // 结局图鉴：挂载时读一次本机记录（导演落结局时已写入）
  const [unlocked] = useState(() => loadUnlocked(script.slug));
  const [minutes] = useState(() => Math.max(1, Math.round((Date.now() - startedAt) / 60000)));

  const ending = script.endings.find((e) => e.id === endingId)!;
  const earned = earnedSeals(script, { flags, rollbacks, quotes: quotes.length, goals });
  const achieved = goals.filter((g) => g.achieved).length;

  return (
    <div className="relative mx-auto flex min-h-full max-w-6xl flex-col justify-center gap-10 px-6 py-12 md:flex-row md:items-center md:gap-16 md:px-12">
      {/* 竖排结局名 */}
      <div className="flex shrink-0 items-start gap-5 self-center md:self-auto">
        <m.h2
          initial={{ opacity: 0, clipPath: "inset(0 0 100% 0)", filter: "blur(6px)" }}
          animate={{ opacity: 1, clipPath: "inset(0 0 0% 0)", filter: "blur(0px)" }}
          transition={{ duration: 1.4, delay: 0.3, ease: EASE }}
          className="title-slip font-serif text-5xl tracking-[0.35em] text-ink [text-shadow:0_0_30px_color-mix(in_srgb,var(--wj-glow-gold)_60%,transparent),0_2px_10px_rgba(0,0,0,0.9)] md:text-6xl"
        >
          {ending.title}
        </m.h2>
        <m.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ duration: 0.8, delay: 1 }}
          className="title-slip font-serif text-sm tracking-[0.5em] text-glow-gold"
        >
          《{script.package.title}》 · 结局
        </m.p>
      </div>

      <div className="flex min-w-0 flex-1 flex-col gap-7">
        <div className="flex flex-col gap-3">
          {ending.lines.map((line, i) => (
            <m.p
              key={line}
              initial={{ opacity: 0, y: 10, filter: "blur(4px)" }}
              animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
              transition={{ duration: 0.8, delay: 0.7 + i * 0.45, ease: EASE }}
              className="measure font-serif text-lg leading-[1.9] text-ink [text-shadow:0_1px_8px_rgba(0,0,0,0.9)]"
            >
              {line}
            </m.p>
          ))}
        </div>

        {/* 成就印章 */}
        <section aria-label="成就印章">
          <ul className="flex flex-wrap gap-4">
            {script.seals.map((seal, i) => {
              const got = earned.has(seal.id);
              return (
                <li key={seal.id} className="flex w-16 flex-col items-center gap-1.5" title={seal.desc}>
                  {got ? (
                    <span
                      className="seal-face animate-seal-stamp grid size-14 place-items-center rounded-md font-serif text-base leading-tight tracking-widest"
                      style={{ animationDelay: `${SEAL_START_S + i * SEAL_GAP_S}s` }}
                    >
                      <span className="title-slip">{seal.glyph}</span>
                    </span>
                  ) : (
                    <span className="grid size-14 rotate-[-6deg] place-items-center rounded-md border border-dashed border-ink-faint/50 font-serif text-base leading-tight tracking-widest text-ink-faint/60">
                      <span className="title-slip">{seal.glyph}</span>
                    </span>
                  )}
                  <span className={`text-2xs ${got ? "text-ink-soft" : "text-ink-faint"}`}>
                    {got ? seal.name : "未得"}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>

        <m.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: SEAL_START_S + script.seals.length * SEAL_GAP_S }}
          className="text-xs tracking-wide text-ink-soft"
        >
          拾句 <span className="text-glow-gold tabular-nums">{quotes.length}/{script.quoteTotal}</span>
          {goals.length > 0 && (
            <>
              <span className="mx-2 text-ink-faint">·</span>续写目标{" "}
              <span className="text-glow-gold tabular-nums">
                {achieved}/{goals.length}
              </span>
            </>
          )}
          <span className="mx-2 text-ink-faint">·</span>回溯{" "}
          <span className="text-glow-jade tabular-nums">{rollbacks}</span> 次
          <span className="mx-2 text-ink-faint">·</span>用时约{" "}
          <span className="tabular-nums">{minutes}</span> 分钟
        </m.p>

        {/* 结局图鉴 */}
        <section aria-label="结局图鉴">
          <p className="mb-2 text-xs text-ink-faint">
            结局图鉴{" "}
            <span className="text-glow-gold tabular-nums">
              {unlocked.length}/{script.endings.length}
            </span>
          </p>
          <ul className="grid grid-cols-3 gap-3">
            {script.endings.map((e) => {
              const seen = unlocked.includes(e.id);
              const current = e.id === endingId;
              return (
                <li
                  key={e.id}
                  className={`relative aspect-[16/10] overflow-hidden rounded-xl border ${
                    current ? "border-glow-gold/70 shadow-[0_0_24px_-6px_var(--wj-glow-gold)]" : "border-glass-edge"
                  }`}
                >
                  <span
                    aria-hidden
                    className={`absolute inset-0 bg-cover bg-center ${seen ? "" : "blur-md brightness-50 grayscale"}`}
                    style={{ backgroundImage: `url(${e.art})` }}
                  />
                  <span className="absolute inset-0 bg-linear-to-t from-black/80 via-black/20 to-transparent" />
                  <span className="absolute inset-x-0 bottom-0 p-2">
                    <span className="block font-serif text-sm text-ink">{seen ? e.title : "？？？"}</span>
                    {!seen && <span className="block text-2xs text-ink-faint">{e.teaser}</span>}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>

        <div className="flex flex-wrap items-center gap-3">
          {canParallel && (
            <Button tone="glow" size="sm" onClick={() => director.parallel()}>
              <BranchIcon />
              平行世界：回到抉择点
            </Button>
          )}
          <Button tone="outline" size="sm" onClick={onReview}>
            回看全剧
          </Button>
          <Button tone="outline" size="sm" onClick={onRestart}>
            从头再演
          </Button>
          <Link href="/demo?shelf=1" className={buttonClass("outline", "sm")}>
            回到书匣
          </Link>
          <button type="button" onClick={onClose} className={buttonClass("quiet", "sm")}>
            留在舞台
          </button>
        </div>
      </div>
    </div>
  );
}
