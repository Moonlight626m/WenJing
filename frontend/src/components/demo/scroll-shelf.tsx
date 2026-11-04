"use client";

import Link from "next/link";
import { m, type Variants } from "motion/react";

import type { ShelfScroll } from "@/lib/demo/catalog";
import { useUnlockedCount } from "@/lib/demo/store";
import { buttonClass } from "@/components/ui/button";

const EASE = [0.2, 0.7, 0.2, 1] as const;

const LIST: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.12, delayChildren: 0.2 } },
};
const ITEM: Variants = {
  hidden: { opacity: 0, y: 24, rotateX: 12, filter: "blur(8px)" },
  show: {
    opacity: 1,
    y: 0,
    rotateX: 0,
    filter: "blur(0px)",
    transition: { duration: 0.7, ease: EASE },
  },
};

/**
 * 书匣：一卷一张卡。能演的卡面是场景画，标着学段、出处、时长和结局解锁进度；
 * 还在做的那卷蒙着一层，写明「下一卷」。
 */
export function ScrollShelf({ scrolls }: { scrolls: ShelfScroll[] }) {
  return (
    <div className="relative mx-auto flex w-full max-w-5xl flex-1 flex-col justify-center gap-8 px-6 py-10">
      <m.div
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.6, ease: EASE }}
        className="text-center"
      >
        <p className="font-serif text-sm tracking-[0.5em] text-glow-gold">书 匣</p>
        <h1 className="text-sheen mt-2 font-serif text-4xl tracking-[0.2em]">选一卷来演</h1>
        <p className="mt-3 text-sm text-ink-soft">
          每一卷由老师上传课文、AI 编成剧本；学生选一个角色进去，演完课文，再续写下去。
        </p>
      </m.div>

      <m.ul
        variants={LIST}
        initial="hidden"
        animate="show"
        className="grid gap-6 [perspective:1200px] md:grid-cols-2"
      >
        {scrolls.map((s) => {
          const playable = s.script !== null;
          return (
            <m.li key={s.slug} variants={ITEM}>
              <article
                className={`glass group relative flex h-full flex-col overflow-hidden rounded-3xl transition-[transform,box-shadow] duration-300 ${
                  playable
                    ? "choice-glow hover:-translate-y-1 hover:shadow-[0_30px_70px_-28px_rgba(0,0,0,0.9)]"
                    : ""
                }`}
              >
                <div className="relative h-52 overflow-hidden border-b border-glass-edge">
                  {s.cover ? (
                    <span
                      aria-hidden
                      className="absolute inset-0 scale-105 bg-cover bg-center transition-transform duration-[1.6s] ease-out group-hover:scale-115"
                      style={{ backgroundImage: `url(${s.cover})` }}
                    />
                  ) : (
                    <span
                      aria-hidden
                      className="absolute inset-0 bg-[radial-gradient(80%_70%_at_50%_30%,color-mix(in_srgb,var(--wj-flag)_30%,transparent),transparent_70%),var(--wj-sunken)]"
                    />
                  )}
                  <span className="absolute inset-0 bg-linear-to-t from-black/70 via-black/10 to-transparent" />
                  <h2 className="title-slip absolute top-4 right-5 border border-glow-gold/40 bg-panel px-2 py-3 font-serif text-xl tracking-[0.3em] text-ink shadow-[0_0_30px_-10px_var(--wj-glow-gold)]">
                    {s.title}
                  </h2>
                  {!playable && (
                    <span className="absolute inset-0 grid place-items-center bg-black/45 backdrop-blur-[2px]">
                      <span className="rounded-full border border-glass-edge bg-panel px-3 py-1 text-xs text-ink-soft">
                        下一卷 · 正在编排
                      </span>
                    </span>
                  )}
                </div>
                <div className="flex flex-1 flex-col gap-3 p-5">
                  <p className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-ink-faint">
                    <span>{s.grade}</span>
                    <span>{s.source}</span>
                    <span>约 {s.minutes} 分钟</span>
                  </p>
                  <p className="font-serif text-base leading-relaxed text-ink-soft">{s.blurb}</p>
                  <p className="flex flex-wrap items-center gap-2 text-xs">
                    <span className="rounded-full border border-flag/40 bg-flag-wash px-2 py-0.5 text-flag">
                      可扮演：{s.roles.join(" / ")}
                    </span>
                    <span className="text-ink-faint">
                      结局{" "}
                      <span className="text-glow-gold tabular-nums">
                        <UnlockedCount slug={s.slug} />/{s.endings}
                      </span>
                    </span>
                  </p>
                  <div className="mt-auto pt-2">
                    {playable ? (
                      <Link href={`/demo/${s.slug}`} className={buttonClass("glow", "md", "w-full")}>
                        开卷演出
                      </Link>
                    ) : (
                      <span className={buttonClass("outline", "md", "w-full opacity-50")}>敬请期待</span>
                    )}
                  </div>
                </div>
              </article>
            </m.li>
          );
        })}
      </m.ul>
    </div>
  );
}

function UnlockedCount({ slug }: { slug: string }) {
  return <>{useUnlockedCount(slug)}</>;
}
