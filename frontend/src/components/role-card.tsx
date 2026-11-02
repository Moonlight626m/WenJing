"use client";

import { useEffect, useRef, useState } from "react";
import { AnimatePresence, m } from "motion/react";

import { useAssetUrl } from "@/lib/asset-url";
import type { CharacterProfile } from "@/lib/contracts/types";
import { initialOf } from "@/lib/stage-cast";
import { useEffectsLevel } from "@/stores/uiStore";
import { Thinking } from "@/components/thinking";
import { Button } from "@/components/ui/button";
import { Tag } from "@/components/ui/tag";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/** 卡片随指针倾斜的最大角度（度）。 */
const TILT_DEG = 7;

/**
 * 指针倾斜：把指针位置换成绕 X/Y 轴的角度写进 CSS 变量，卡片像被拿在手里端详。
 * 只写变量、不重渲染；简洁特效档与触屏不启用。
 */
function useTilt(enabled: boolean) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!enabled || !el) return;
    if (!window.matchMedia("(pointer: fine)").matches) return;
    function onMove(e: PointerEvent) {
      const rect = el!.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width - 0.5;
      const y = (e.clientY - rect.top) / rect.height - 0.5;
      el!.style.setProperty("--wj-ry", `${(x * TILT_DEG * 2).toFixed(2)}deg`);
      el!.style.setProperty("--wj-rx", `${(-y * TILT_DEG * 2).toFixed(2)}deg`);
    }
    function onLeave() {
      el!.style.setProperty("--wj-rx", "0deg");
      el!.style.setProperty("--wj-ry", "0deg");
    }
    el.addEventListener("pointermove", onMove);
    el.addEventListener("pointerleave", onLeave);
    return () => {
      el.removeEventListener("pointermove", onMove);
      el.removeEventListener("pointerleave", onLeave);
    };
  }, [enabled]);
  return ref;
}

/**
 * 选角卡：上半是角色的立绘（缺图时是竖排名牌加一团光晕），下半是小传与性格，
 * 底部「扮演此角色」。悬停时卡片随指针倾斜、边框亮起流光；选定后朱砂描边，
 * 盖一方「已选」印。
 */
export function RoleCard({
  profile,
  playable,
  selected,
  submitting,
  onSelect,
}: {
  profile: CharacterProfile;
  playable: boolean;
  selected: boolean;
  submitting: boolean;
  onSelect: () => void;
}) {
  const full = useEffectsLevel() === "full";
  const tiltRef = useTilt(full);
  const { url: fullbodyUrl } = useAssetUrl(profile.fullbody_asset);
  const { url: avatarUrl } = useAssetUrl(fullbodyUrl ? null : profile.avatar_asset);
  const imageUrl = fullbodyUrl ?? avatarUrl;
  const traits = profile.personality_traits.map((t) => t.label);

  return (
    <article
      ref={tiltRef}
      data-chosen={selected}
      className={`choice-glow group relative flex flex-col overflow-hidden rounded-3xl border bg-glass backdrop-blur-md transition-[transform,box-shadow] duration-200 ease-out ${
        selected
          ? "border-flag/60 shadow-[0_0_40px_-12px_var(--wj-flag)]"
          : "border-glass-edge hover:shadow-[0_24px_60px_-24px_rgba(0,0,0,0.8)]"
      }`}
      style={{
        transform:
          "perspective(900px) rotateX(var(--wj-rx, 0deg)) rotateY(var(--wj-ry, 0deg))",
      }}
    >
      {/* 立绘区 */}
      <div className="relative grid h-56 place-items-center overflow-hidden border-b border-glass-edge bg-sunken/40">
        <span
          aria-hidden
          className={`absolute top-1/2 left-1/2 size-48 -translate-x-1/2 -translate-y-1/2 rounded-full blur-3xl ${
            selected ? "bg-flag/30" : "bg-glow-gold/20 group-hover:bg-glow-jade/25"
          } transition-colors duration-500`}
        />
        {imageUrl ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={imageUrl}
            alt={`${profile.name}的立绘`}
            className={`relative h-full w-full ${
              fullbodyUrl ? "object-contain p-3" : "object-cover"
            }`}
          />
        ) : (
          <span
            aria-hidden
            className={`title-slip relative font-serif text-5xl tracking-[0.3em] [text-shadow:0_0_24px_currentColor] ${
              selected ? "text-flag" : "text-glow-gold"
            }`}
          >
            {initialOf(profile.name)}
          </span>
        )}

        <AnimatePresence>
          {selected && (
            <m.span
              aria-hidden
              initial={{ scale: 1.8, rotate: -20, opacity: 0 }}
              animate={{ scale: 1, rotate: -8, opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ type: "spring", stiffness: 260, damping: 15 }}
              className="absolute top-4 right-4 grid size-14 place-items-center rounded-md bg-flag font-serif text-lg leading-none text-canvas shadow-[0_0_24px_-6px_var(--wj-flag)]"
            >
              已选
            </m.span>
          )}
        </AnimatePresence>
      </div>

      {/* 小传区 */}
      <div className="flex flex-1 flex-col gap-2 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="font-serif text-2xl text-ink">{profile.name}</h2>
          {playable && <Tag tone="accent">可扮演</Tag>}
          {selected && <Tag tone="flag">你</Tag>}
        </div>
        {profile.public_background && (
          <p className="line-clamp-4 text-sm leading-relaxed text-ink-soft">
            {profile.public_background}
          </p>
        )}
        {traits.length > 0 && (
          <ul className="flex flex-wrap gap-1.5" aria-label="性格">
            {traits.map((label) => (
              <li
                key={label}
                className="rounded-full border border-glow-gold/30 px-2 py-0.5 text-2xs text-glow-gold"
              >
                {label}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-auto pt-2">
          <Button
            tone={selected ? "outline" : "glow"}
            size="sm"
            onClick={onSelect}
            disabled={submitting || selected}
            className="w-full"
          >
            {selected ? "已选" : submitting ? "生成首幕中…" : "扮演此角色"}
          </Button>
        </div>
      </div>
    </article>
  );
}

/** 等首幕时轮播角色小传的间隔。 */
const ROTATE_MS = 4500;

/**
 * 首幕生成的等待过场：真实 LLM 要为每个角色写提议再逐一校验，十几秒到几分钟。
 * 这段时间铺满一屏：你选的角色名、轮播其他角色的小传，加一个已等待秒数，
 * 让学生知道它在走、也顺手认识一下同台的人。
 */
export function FirstActWaiting({
  role,
  scriptTitle,
  characters,
  since,
}: {
  role: string;
  scriptTitle: string | null;
  characters: CharacterProfile[];
  since: number;
}) {
  const others = characters.filter((c) => c.name !== role && c.public_background);
  const [index, setIndex] = useState(0);

  useEffect(() => {
    if (others.length < 2) return;
    const timer = setInterval(() => setIndex((i) => i + 1), ROTATE_MS);
    return () => clearInterval(timer);
  }, [others.length]);

  const current = others.length > 0 ? others[index % others.length] : null;

  return (
    <m.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.5 }}
      className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-black/75 px-6 text-center backdrop-blur-sm"
    >
      <p className="font-serif text-sm tracking-[0.5em] text-glow-gold">
        {scriptTitle ? `《${scriptTitle}》` : "第一幕"}
      </p>
      <m.p
        initial={{ opacity: 0, clipPath: "inset(0 100% 0 0)" }}
        animate={{ opacity: 1, clipPath: "inset(0 0% 0 0)" }}
        transition={{ duration: 1.1, delay: 0.2, ease: EASE }}
        className="mt-4 font-serif text-xl text-ink-soft"
      >
        你将成为
      </m.p>
      <m.p
        initial={{ opacity: 0, scale: 0.92, filter: "blur(8px)" }}
        animate={{ opacity: 1, scale: 1, filter: "blur(0px)" }}
        transition={{ duration: 0.9, delay: 0.5, ease: EASE }}
        className="text-sheen mt-2 font-serif text-5xl tracking-[0.3em] md:text-6xl"
      >
        {role}
      </m.p>

      <div className="mt-10 min-h-28 w-full max-w-md">
        <AnimatePresence mode="wait">
          {current && (
            <m.div
              key={current.name}
              initial={{ opacity: 0, y: 10 }}
              animate={{ opacity: 1, y: 0 }}
              exit={{ opacity: 0, y: -10 }}
              transition={{ duration: 0.5 }}
              className="glass rounded-2xl px-5 py-4 text-left"
            >
              <p className="text-xs text-ink-faint">同台的人</p>
              <p className="mt-1 font-serif text-lg text-glow-gold">{current.name}</p>
              <p className="mt-1 line-clamp-3 text-sm leading-relaxed text-ink-soft">
                {current.public_background}
              </p>
            </m.div>
          )}
        </AnimatePresence>
      </div>

      <Thinking label="正在拉开第一幕" since={since} className="mt-8 text-sm" />
      <p className="measure mt-3 text-xs text-ink-faint">
        要为每个角色写好开场并逐一校验，通常十几秒到几分钟。会话已保存，离开也不会丢。
      </p>
    </m.div>
  );
}
