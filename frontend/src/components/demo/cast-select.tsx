"use client";

import { useEffect } from "react";
import Link from "next/link";
import { m, type Variants } from "motion/react";

import type { DemoScript } from "@/lib/demo/types";
import { initialOf } from "@/lib/stage-cast";
import { useEffectsLevel, useUiStore } from "@/stores/uiStore";
import { StageParticles } from "@/components/stage-particles";
import { Button, buttonClass } from "@/components/ui/button";
import { MotionRoot } from "@/components/ui/motion-root";

const EASE = [0.2, 0.7, 0.2, 1] as const;

const LIST: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.08, delayChildren: 0.35 } },
};
const ITEM: Variants = {
  hidden: { opacity: 0, y: 18, filter: "blur(6px)" },
  show: { opacity: 1, y: 0, filter: "blur(0px)", transition: { duration: 0.5, ease: EASE } },
};

/**
 * 选角：你来演的那一位放大摆在左边，其余角色列在右边，标明由 AI 来演。
 * 这一页要讲清楚产品的核心——学生只演一个人，同台的其他人都是 AI。
 */
export function CastSelect({ script, onStart }: { script: DemoScript; onStart: () => void }) {
  const full = useEffectsLevel() === "full";
  const hydrateEffects = useUiStore((s) => s.hydrateEffects);
  const player = script.package.characters.find((c) => c.name === script.playerRole)!;
  const others = script.package.characters.filter((c) => c.name !== script.playerRole);

  useEffect(() => {
    hydrateEffects();
  }, [hydrateEffects]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Enter" || e.key === "PageDown" || e.key === "ArrowRight") {
        e.preventDefault();
        onStart();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onStart]);

  return (
    <MotionRoot>
      <div className="relative flex min-h-0 flex-1 flex-col overflow-y-auto">
        <div
          aria-hidden
          className="fixed inset-0 scale-110 bg-cover bg-center opacity-35 blur-sm"
          style={{ backgroundImage: `url(${script.shelf.cover})` }}
        />
        <div aria-hidden className="stage-vignette fixed inset-0" />
        {full && <StageParticles />}

        <header className="relative flex items-center justify-between px-6 pt-5">
          <Link href="/demo?shelf=1" className={buttonClass("quiet", "xs")}>
            ← 书匣
          </Link>
          <span className="text-xs text-glow-gold">演示台本 · 预录</span>
        </header>

        <div className="relative mx-auto flex w-full max-w-6xl flex-1 flex-col justify-center gap-8 px-6 py-8">
          <m.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: EASE }}
            className="text-center"
          >
            <p className="font-serif text-sm tracking-[0.5em] text-glow-gold">选 角</p>
            <h1 className="text-sheen mt-2 font-serif text-4xl tracking-[0.2em] md:text-5xl">
              《{script.package.title}》
            </h1>
            <p className="mt-3 text-sm text-ink-soft">
              你只演其中一位，同台的其他人都由 AI 来演——他们按课文里的性格说话，也会接住你的临场发挥。
            </p>
          </m.div>

          <m.div
            variants={LIST}
            initial="hidden"
            animate="show"
            className="grid gap-5 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]"
          >
            {/* 你演的角色 */}
            <m.article
              variants={ITEM}
              className="glass glow-border relative flex flex-col overflow-hidden rounded-3xl"
            >
              <div className="relative grid h-60 place-items-center overflow-hidden border-b border-glass-edge">
                <span aria-hidden className="absolute size-56 rounded-full bg-flag/25 blur-3xl" />
                <span
                  aria-hidden
                  className="title-slip relative font-serif text-7xl tracking-[0.3em] text-flag [text-shadow:0_0_30px_currentColor]"
                >
                  {initialOf(player.name)}
                </span>
                <span className="seal-face absolute top-4 right-4 grid size-14 rotate-[-8deg] place-items-center rounded-md font-serif text-lg leading-none">
                  你
                </span>
              </div>
              <div className="flex flex-1 flex-col gap-2.5 p-5">
                <div className="flex items-baseline gap-3">
                  <h2 className="font-serif text-3xl text-ink">{player.name}</h2>
                  <span className="text-xs text-flag">{script.castNotes[player.name]}</span>
                </div>
                <p className="text-sm leading-relaxed text-ink-soft">{player.public_background}</p>
                <ul className="flex flex-wrap gap-1.5" aria-label="性格">
                  {player.personality_traits.map((t) => (
                    <li
                      key={t.label}
                      title={t.evidence}
                      className="rounded-full border border-glow-gold/30 px-2 py-0.5 text-2xs text-glow-gold"
                    >
                      {t.label}
                    </li>
                  ))}
                </ul>
                <div className="mt-auto pt-3">
                  <Button tone="glow" size="md" onClick={onStart} className="w-full">
                    由我来演，开场
                  </Button>
                  <p className="mt-2 text-center text-2xs text-ink-faint">回车或翻页笔也能开场</p>
                </div>
              </div>
            </m.article>

            {/* 同台的 AI 角色 */}
            <div className="grid content-start gap-3 sm:grid-cols-2">
              {others.map((c) => (
                <m.article
                  key={c.name}
                  variants={ITEM}
                  className="glass flex gap-3.5 rounded-2xl p-4"
                >
                  <span
                    aria-hidden
                    className="grid size-12 shrink-0 place-items-center rounded-full border border-glow-gold/40 bg-sunken/50 font-serif text-xl text-glow-gold [text-shadow:0_0_14px_currentColor]"
                  >
                    {initialOf(c.name)}
                  </span>
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-baseline gap-2">
                      <h3 className="font-serif text-lg text-ink">{c.name}</h3>
                      <span className="rounded-full border border-glow-jade/40 px-1.5 py-px text-2xs text-glow-jade">
                        AI 扮演
                      </span>
                    </div>
                    <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-ink-soft">
                      {c.public_background}
                    </p>
                    {script.castNotes[c.name] && (
                      <p className="mt-1 text-2xs text-ink-faint">{script.castNotes[c.name]}</p>
                    )}
                  </div>
                </m.article>
              ))}
            </div>
          </m.div>
        </div>
      </div>
    </MotionRoot>
  );
}
