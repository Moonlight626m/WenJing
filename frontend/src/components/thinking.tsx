"use client";

import { useEffect, useState } from "react";

/** 三点颜色依次是青碧、泥金、朱砂，和流光描边同一组。 */
const DOTS = ["bg-glow-jade", "bg-glow-gold", "bg-flag"];

/** 从 `since` 起已过的整秒数，每秒刷新一次；`since` 为空时不起计时器。 */
function useElapsedSeconds(since: number | undefined): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (since === undefined) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [since]);
  if (since === undefined) return 0;
  return Math.max(0, Math.floor((now - since) / 1000));
}

/**
 * 「正在推进」指示：三颗墨点依次晕开，加一句说明。
 *
 * 真实 LLM 一条命令要等几十秒，光有一行闪烁的字容易让人以为卡住了；
 * 给了 `since` 就在 3 秒后补一个已等待秒数，让学生知道它还在走。
 * 文字用朱砂，沿用「正在推进 = 在场」的语义。
 *
 * 同一屏可能出现两处（顶栏与抉择卡），只让一处当 live region（`announce`），
 * 否则读屏会把同一句播两遍。秒数不进朗读，不然每秒都要念一次。
 */
export function Thinking({
  label,
  since,
  announce = true,
  className = "",
}: {
  label: string;
  since?: number;
  announce?: boolean;
  className?: string;
}) {
  const elapsed = useElapsedSeconds(since);

  return (
    <span
      role={announce ? "status" : undefined}
      className={`inline-flex items-center gap-2 text-flag ${className}`}
    >
      <span aria-hidden className="flex items-center gap-1">
        {DOTS.map((dot, i) => (
          <span
            key={dot}
            className={`animate-ink-breathe size-1.5 rounded-full ${dot}`}
            style={{ animationDelay: `${i * 0.18}s` }}
          />
        ))}
      </span>
      <span>{label}</span>
      {since !== undefined && elapsed >= 3 && (
        <span aria-hidden className="text-ink-faint tabular-nums">
          已等 {elapsed} 秒
        </span>
      )}
    </span>
  );
}
