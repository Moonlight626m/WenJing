"use client";

import { useEffect, useId, useState } from "react";
import { AnimatePresence, m } from "motion/react";

import type { DemoDirector } from "@/lib/demo/director";
import { useDemoStore } from "@/lib/demo/store";
import { useGameStore } from "@/stores/gameStore";
import { useEffectsLevel } from "@/stores/uiStore";
import { BookIcon, BranchIcon, NextIcon, PauseIcon, PlayIcon } from "@/components/ui/icons";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/** 拾句卡在屏幕中央停留的时长，之后飞进顶上的书匣。 */
const QUOTE_HOLD_MS = 2300;

/**
 * 拾句：演到课文里的关键句时，那一句原文以卡片浮出，停一会儿再飞进顶上的书匣。
 * 书匣里攒下的句子在结局时清点。
 */
export function QuoteCatch() {
  const catching = useDemoStore((s) => s.catching);

  useEffect(() => {
    if (!catching) return;
    const timer = setTimeout(() => useDemoStore.setState({ catching: null }), QUOTE_HOLD_MS);
    return () => clearTimeout(timer);
  }, [catching]);

  return (
    <div
      aria-live="polite"
      className="pointer-events-none absolute inset-0 z-30 grid place-items-center px-6 pb-[18%]"
    >
      <AnimatePresence>
        {catching && (
          <m.figure
            key={catching.text}
            initial={{ opacity: 0, y: 28, scale: 0.9, filter: "blur(10px)" }}
            animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
            exit={{
              opacity: 0,
              y: "-34vh",
              scale: 0.16,
              rotate: -6,
              transition: { duration: 0.75, ease: [0.55, 0, 0.75, 0.2] },
            }}
            transition={{ duration: 0.6, ease: EASE }}
            className="glass relative max-w-xl rounded-3xl px-8 pt-6 pb-5 text-center"
          >
            <span
              aria-hidden
              className="seal-face absolute -top-4 -left-4 grid size-11 rotate-[-8deg] place-items-center rounded-md font-serif text-sm leading-none"
            >
              拾句
            </span>
            <blockquote className="font-serif text-xl leading-relaxed text-ink md:text-2xl">
              「{catching.text}」
            </blockquote>
            <figcaption className="mt-3 text-xs tracking-wider text-glow-gold">
              {catching.note} · 收入书匣
            </figcaption>
          </m.figure>
        )}
      </AnimatePresence>
    </div>
  );
}

/**
 * 命运抉择：摆出抉择卡时画面褪色（演出页根节点的 `data-fate`，见 globals.css），
 * 上方写出「命运抉择」四个字，四周压一圈朱砂色的暗角；选定的一刻墨点溅开。
 */
export function FateOverlay() {
  const fate = useDemoStore((s) => s.fate);
  const full = useEffectsLevel() === "full";

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 z-20 overflow-hidden">
      <div
        className={`absolute inset-0 transition-opacity duration-1000 ${
          fate === "idle" ? "opacity-0" : "opacity-100"
        }`}
        style={{
          background:
            "radial-gradient(90% 75% at 50% 45%, transparent 40%, color-mix(in srgb, var(--wj-flag) 22%, transparent) 85%, color-mix(in srgb, var(--wj-flag) 34%, transparent) 100%)",
        }}
      />
      <AnimatePresence>
        {fate === "choosing" && (
          <m.div
            key="fate-title"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0, transition: { duration: 0.4 } }}
            className="absolute inset-x-0 top-[14%] flex flex-col items-center"
          >
            <p className="animate-brush-write font-serif text-4xl tracking-[0.55em] text-ink [text-shadow:0_0_28px_var(--wj-flag),0_2px_8px_rgba(0,0,0,0.9)] md:text-6xl">
              命运抉择
            </p>
            <m.span
              initial={{ scaleX: 0 }}
              animate={{ scaleX: 1 }}
              transition={{ duration: 0.9, delay: 0.6, ease: EASE }}
              className="mt-4 block h-px w-64 bg-linear-to-r from-transparent via-flag to-transparent"
            />
            <m.p
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6, delay: 1 }}
              className="mt-3 font-serif text-sm tracking-widest text-ink-soft"
            >
              这一选，故事将走向不同的结局
            </m.p>
          </m.div>
        )}
      </AnimatePresence>
      {fate === "splash" && full && <InkSplash />}
    </div>
  );
}

/** 墨点：一大团加十几颗飞溅的小点，边缘用噪声啃出毛边。 */
function InkSplash() {
  const filterId = `ink${useId().replace(/[^a-zA-Z0-9_-]/g, "")}`;
  const drops: [number, number, number][] = [
    [62, 70, 14], [330, 96, 18], [300, 318, 11], [96, 300, 20], [200, 36, 9],
    [366, 210, 8], [30, 186, 10], [240, 362, 13], [140, 120, 7], [276, 140, 6],
    [120, 352, 6], [352, 340, 7],
  ];
  return (
    <svg
      viewBox="0 0 400 400"
      className="animate-ink-splash absolute top-1/2 left-1/2 size-[min(78vmin,44rem)] -translate-x-1/2 -translate-y-1/2"
    >
      <defs>
        <filter id={filterId} x="-20%" y="-20%" width="140%" height="140%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="3" seed="7" />
          <feDisplacementMap in="SourceGraphic" scale="34" />
        </filter>
      </defs>
      <g filter={`url(#${filterId})`} fill="var(--wj-flag)">
        <circle cx="200" cy="205" r="92" opacity="0.5" />
        <circle cx="186" cy="190" r="58" opacity="0.45" />
        <ellipse cx="292" cy="246" rx="70" ry="10" transform="rotate(32 292 246)" opacity="0.4" />
        <ellipse cx="104" cy="160" rx="64" ry="8" transform="rotate(-24 104 160)" opacity="0.4" />
        {drops.map(([x, y, r]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r={r} opacity="0.55" />
        ))}
      </g>
      <g fill="var(--wj-glow-gold)" opacity="0.8">
        <circle cx="152" cy="92" r="2.4" />
        <circle cx="318" cy="168" r="1.8" />
        <circle cx="86" cy="248" r="2" />
        <circle cx="262" cy="330" r="1.6" />
      </g>
    </svg>
  );
}

/**
 * 「试试这样说」：续写里允许自己写时，在抉择卡上方给演示者几句现成的话，点一下就发出。
 * 也可以照常在输入框里写——比如请在场的老师出一句。
 */
export function SuggestionChips() {
  const suggestions = useDemoStore((s) => s.suggestions);
  const interaction = useGameStore((s) => s.interaction);
  const pending = useGameStore((s) => s.pending);
  const allowed = useGameStore((s) => s.allowedCommands);
  const submit = useGameStore((s) => s.submitCommand);
  const show =
    suggestions.length > 0 && interaction !== null && !pending && allowed.includes("free_input");

  return (
    <AnimatePresence>
      {show && (
        <m.div
          key={interaction?.interaction_id}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0, y: 6 }}
          transition={{ duration: 0.35, ease: EASE }}
          className="flex flex-wrap items-center gap-2 px-1"
        >
          <span className="text-xs text-ink-faint">试试这样说</span>
          {suggestions.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => submit("free_input", { text }, "自由输入")}
              className="rounded-full border border-glass-edge bg-glass px-3 py-1 font-serif text-sm text-ink-soft backdrop-blur-md transition-[color,border-color,box-shadow] duration-200 hover:border-glow-jade/50 hover:text-ink hover:shadow-[0_0_16px_-4px_var(--wj-glow-jade)]"
            >
              {text}
            </button>
          ))}
        </m.div>
      )}
    </AnimatePresence>
  );
}

/** 焦点在可输入元素里时，空格与字母键是在打字，不是在遥控。 */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

/**
 * 演示控制条：悬在舞台正上方。标明这是预录台本，带暂停、下一句、平行世界与书匣。
 *
 * 快捷键照翻页笔来：空格 / → / PageDown 下一句，PageUp / B 平行世界，P 暂停。
 */
export function PresenterBar({
  director,
  quoteTotal,
}: {
  director: DemoDirector;
  quoteTotal: number;
}) {
  const paused = useDemoStore((s) => s.paused);
  const canParallel = useDemoStore((s) => s.canParallel);
  const quotes = useDemoStore((s) => s.quotes);
  const [shelfOpen, setShelfOpen] = useState(false);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (e.defaultPrevented || e.isComposing) return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (isTypingTarget(e.target)) return;
      if (e.key === " " || e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        director.next();
      } else if (e.key === "p" || e.key === "P") {
        e.preventDefault();
        director.setPaused(!useDemoStore.getState().paused);
      } else if (e.key === "b" || e.key === "B" || e.key === "PageUp") {
        e.preventDefault();
        director.parallel();
      }
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [director]);

  const button =
    "flex items-center gap-1.5 rounded-full px-2.5 py-1 transition-[color,background-color] duration-150 hover:bg-surface/60 hover:text-ink disabled:pointer-events-none disabled:opacity-40";

  return (
    <div className="absolute top-3 left-1/2 z-30 -translate-x-1/2">
      <div className="glass flex items-center gap-0.5 rounded-full py-1 pr-1 pl-3 text-xs text-ink-soft">
        <span className="mr-1.5 flex items-center gap-1.5 whitespace-nowrap text-glow-gold">
          <span aria-hidden className="size-1.5 rounded-full bg-glow-gold shadow-[0_0_8px_var(--wj-glow-gold)]" />
          演示台本 · 预录
        </span>
        <button
          type="button"
          className={button}
          onClick={() => director.setPaused(!paused)}
          aria-pressed={paused}
          title="暂停 / 继续（P）"
        >
          {paused ? <PlayIcon /> : <PauseIcon />}
          <span className="hidden md:inline">{paused ? "继续" : "暂停"}</span>
        </button>
        <button type="button" className={button} onClick={() => director.next()} title="下一句（空格）">
          <NextIcon />
          <span className="hidden md:inline">下一句</span>
        </button>
        <button
          type="button"
          className={button}
          onClick={() => director.parallel()}
          disabled={!canParallel}
          title="平行世界：回到命运抉择（B）"
        >
          <BranchIcon />
          <span className="hidden md:inline">平行世界</span>
        </button>
        <button
          type="button"
          className={`${button} ${shelfOpen ? "bg-surface/60 text-ink" : ""}`}
          onClick={() => setShelfOpen((v) => !v)}
          aria-expanded={shelfOpen}
          title="书匣：拾到的原句"
        >
          <BookIcon />
          <span className="tabular-nums">
            {quotes.length}/{quoteTotal}
          </span>
        </button>
      </div>

      <AnimatePresence>
        {shelfOpen && (
          <m.ol
            initial={{ opacity: 0, y: -6 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -6 }}
            transition={{ duration: 0.25, ease: EASE }}
            className="glass absolute top-full left-1/2 mt-2 flex w-80 -translate-x-1/2 flex-col gap-2 rounded-2xl p-3"
          >
            {quotes.length === 0 && (
              <li className="text-xs text-ink-faint">还没有拾到句子。演到课文里的关键句时，它会自己飞进来。</li>
            )}
            {quotes.map((q) => (
              <li key={q.text} className="border-l-2 border-glow-gold/50 pl-2.5">
                <p className="font-serif text-sm leading-relaxed text-ink">「{q.text}」</p>
                <p className="mt-0.5 text-2xs text-ink-faint">{q.note}</p>
              </li>
            ))}
          </m.ol>
        )}
      </AnimatePresence>
    </div>
  );
}
