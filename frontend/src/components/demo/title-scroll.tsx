"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, m } from "motion/react";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/** 画轴展开用时。 */
const UNROLL_S = 1.6;

/**
 * 开卷：两根画轴并在一起躺在幕布中央，点一下（或按空格、回车、翻页笔）向两边展开，
 * 露出一幅水墨山水和竖排的「文境」题签；再点一下入卷，进书匣选剧本。
 */
export function TitleScroll({ onEnter }: { onEnter: () => void }) {
  const [open, setOpen] = useState(false);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!open) return;
    const timer = setTimeout(() => setReady(true), (UNROLL_S + 0.9) * 1000);
    return () => clearTimeout(timer);
  }, [open]);

  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if (![" ", "Enter", "PageDown", "ArrowRight"].includes(e.key)) return;
      e.preventDefault();
      if (!open) setOpen(true);
      else if (ready) onEnter();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, ready, onEnter]);

  return (
    <div className="relative flex flex-1 flex-col items-center justify-center gap-10 px-4">
      <button
        type="button"
        onClick={() => (open ? ready && onEnter() : setOpen(true))}
        aria-label={open ? "入卷" : "开卷"}
        className="group relative h-[min(64vh,30rem)] w-[min(88vw,62rem)] cursor-pointer focus-visible:outline-none"
      >
        {/* 画心：从中线向两边展开 */}
        <m.div
          initial={false}
          animate={{ clipPath: open ? "inset(0 0% 0 0%)" : "inset(0 50% 0 50%)" }}
          transition={{ duration: UNROLL_S, ease: [0.6, 0.05, 0.25, 1] }}
          className="scroll-paper absolute inset-y-[4%] inset-x-[2.5%] overflow-hidden rounded-[3px] shadow-[0_30px_80px_-20px_rgba(0,0,0,0.9)]"
        >
          <Landscape />
          <div className="absolute inset-y-[8%] right-[9%] flex items-start gap-4">
            <div className="flex flex-col items-center gap-5">
              <m.h1
                initial={false}
                animate={open ? { opacity: 1, y: 0, filter: "blur(0px)" } : { opacity: 0, y: -10, filter: "blur(6px)" }}
                transition={{ duration: 1.1, delay: open ? UNROLL_S * 0.7 : 0, ease: EASE }}
                className="title-slip font-serif text-[clamp(3rem,8vh,5.5rem)] font-semibold tracking-[0.3em] text-[#1d1610]"
              >
                文境
              </m.h1>
              <m.span
                aria-hidden
                initial={false}
                animate={open ? { opacity: 1, scale: 1, rotate: -6 } : { opacity: 0, scale: 1.8, rotate: -18 }}
                transition={{ type: "spring", stiffness: 260, damping: 16, delay: open ? UNROLL_S + 0.3 : 0 }}
                className="grid size-[clamp(2.75rem,7vh,4rem)] place-items-center rounded-sm bg-[#b0372a] font-serif text-[clamp(0.8rem,2vh,1.1rem)] leading-tight text-[#f5e9d6] shadow-[inset_0_0_0_2px_rgba(255,255,255,0.25)]"
              >
                <span className="title-slip">文境</span>
              </m.span>
            </div>
            <m.p
              initial={false}
              animate={open ? { opacity: 1 } : { opacity: 0 }}
              transition={{ duration: 1, delay: open ? UNROLL_S * 0.7 + 0.5 : 0 }}
              className="title-slip mt-6 font-serif text-[clamp(0.85rem,2vh,1.1rem)] tracking-[0.5em] text-[#4a3d2e]"
            >
              进入课文，成为其中的人
            </m.p>
          </div>
        </m.div>

        {/* 两根画轴 */}
        {(["left", "right"] as const).map((side) => (
          <m.span
            key={side}
            aria-hidden
            initial={false}
            animate={{ left: open ? (side === "left" ? "0%" : "100%") : "50%" }}
            transition={{ duration: UNROLL_S, ease: [0.6, 0.05, 0.25, 1] }}
            className="scroll-rod absolute inset-y-0 w-[clamp(14px,1.6vw,22px)] -translate-x-1/2 rounded-full"
          >
            <span className="absolute -top-2 left-1/2 h-3 w-[160%] -translate-x-1/2 rounded-full bg-linear-to-b from-[#c9a35a] to-[#7a5a24]" />
            <span className="absolute -bottom-2 left-1/2 h-3 w-[160%] -translate-x-1/2 rounded-full bg-linear-to-b from-[#c9a35a] to-[#7a5a24]" />
          </m.span>
        ))}

        {/* 合着的时候，轴上挂一枚签 */}
        <AnimatePresence>
          {!open && (
            <m.span
              key="tag"
              initial={{ opacity: 0, y: 6 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, transition: { duration: 0.2 } }}
              transition={{ duration: 0.8, delay: 0.4 }}
              className="title-slip absolute top-[18%] left-1/2 ml-6 border border-glow-gold/40 bg-panel px-2 py-4 font-serif text-lg tracking-[0.4em] text-ink shadow-[0_0_30px_-10px_var(--wj-glow-gold)]"
            >
              文境
            </m.span>
          )}
        </AnimatePresence>
      </button>

      <AnimatePresence mode="wait">
        <m.p
          key={open ? (ready ? "enter" : "opening") : "open"}
          initial={{ opacity: 0, y: 6 }}
          animate={{ opacity: 1, y: 0 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.5 }}
          className="h-5 font-serif text-sm tracking-[0.4em] text-ink-soft"
        >
          {!open ? (
            <span className="animate-pulse">点击开卷</span>
          ) : ready ? (
            <span className="animate-pulse">入卷 →</span>
          ) : null}
        </m.p>
      </AnimatePresence>
    </div>
  );
}

/** 画心上的水墨山水：远山、近山、一叶扁舟、一轮淡月。全是矢量，不依赖图片。 */
function Landscape() {
  return (
    <svg
      viewBox="0 0 1000 480"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden
      className="absolute inset-0 h-full w-full"
    >
      <defs>
        <filter id="title-ink" x="-10%" y="-10%" width="120%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.012 0.04" numOctaves="3" seed="3" />
          <feDisplacementMap in="SourceGraphic" scale="14" />
          <feGaussianBlur stdDeviation="0.8" />
        </filter>
        <linearGradient id="title-far" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#6d6a62" stopOpacity="0.38" />
          <stop offset="1" stopColor="#6d6a62" stopOpacity="0" />
        </linearGradient>
        <linearGradient id="title-near" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#2c2a26" stopOpacity="0.82" />
          <stop offset="0.7" stopColor="#2c2a26" stopOpacity="0.15" />
          <stop offset="1" stopColor="#2c2a26" stopOpacity="0" />
        </linearGradient>
      </defs>
      <circle cx="250" cy="120" r="46" fill="#c9a35a" opacity="0.18" />
      <g filter="url(#title-ink)">
        <path
          d="M0 300 C 80 230 130 250 190 200 S 300 150 360 210 S 470 260 540 190 S 650 120 720 200 S 860 250 1000 220 L1000 480 L0 480 Z"
          fill="url(#title-far)"
        />
        <path
          d="M-20 380 C 60 300 120 330 170 270 S 260 220 300 290 S 380 360 450 330 S 560 300 600 360 L 600 480 L -20 480 Z"
          fill="url(#title-near)"
        />
        <path d="M520 420 C 600 380 700 400 760 370 S 900 360 1020 400 L1020 480 L520 480 Z" fill="url(#title-near)" opacity="0.6" />
      </g>
      {/* 扁舟与渔人 */}
      <g transform="translate(470 392)" fill="#231d17" opacity="0.85">
        <path d="M-34 0 Q 0 10 34 0 Q 20 6 0 7 Q -20 6 -34 0 Z" />
        <path d="M-4 -1 L -2 -16 L 3 -16 L 4 -1 Z" />
        <path d="M-8 -16 Q 0 -24 8 -16 Z" />
        <path d="M2 -12 L 30 -32" stroke="#231d17" strokeWidth="1.2" />
      </g>
      <path d="M380 404 h 50 M 510 408 h 70 M 300 414 h 40" stroke="#231d17" strokeOpacity="0.25" strokeWidth="1.2" />
    </svg>
  );
}
