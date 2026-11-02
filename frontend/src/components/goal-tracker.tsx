"use client";

import { useState } from "react";
import { AnimatePresence, m } from "motion/react";

import type { Stage3Goal } from "@/lib/contracts/types";
import { CheckIcon } from "@/components/ui/icons";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/**
 * 续写目标追踪：浮在舞台左上（头像组下面）的一张小卡，列出编剧定下的 2–3 个小目标，
 * 达成的打上泥金勾。全部达成时续写自然收束（引擎侧），这里给出进度。
 *
 * 可以收成一枚「续写目标 1/3」的小签，免得挡住立绘。
 */
export function GoalTracker({
  goals,
  defaultCollapsed = false,
}: {
  goals: Stage3Goal[];
  /** 窄屏上舞台视口很矮，默认收成小签，点开再看 */
  defaultCollapsed?: boolean;
}) {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  if (goals.length === 0) return null;

  const done = goals.filter((g) => g.achieved).length;
  const progress = `${done}/${goals.length}`;

  return (
    <section
      aria-label="续写目标"
      className="glass w-68 max-w-full overflow-hidden rounded-2xl"
    >
      <button
        type="button"
        onClick={() => setCollapsed((v) => !v)}
        aria-expanded={!collapsed}
        className="flex w-full items-center gap-2 px-3 py-2 text-left"
      >
        <span className="font-serif text-sm whitespace-nowrap text-ink">续写目标</span>
        <span aria-live="polite" className="text-xs text-glow-gold tabular-nums">
          {progress}
        </span>
        <span className="relative ml-auto h-1 w-16 overflow-hidden rounded-full bg-rule">
          <m.span
            className="absolute inset-y-0 left-0 rounded-full bg-linear-to-r from-glow-gold to-glow-jade"
            initial={false}
            animate={{ width: `${(done / goals.length) * 100}%` }}
            transition={{ duration: 0.6, ease: EASE }}
          />
        </span>
      </button>

      <AnimatePresence initial={false}>
        {!collapsed && (
          <m.ol
            key="goals"
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.3, ease: EASE }}
            className="flex flex-col gap-1.5 px-3 pb-3"
          >
            {goals.map((goal) => (
              <li key={goal.goal_id} className="flex items-start gap-2">
                <span className="relative mt-0.5 grid size-4 shrink-0 place-items-center">
                  <AnimatePresence initial={false} mode="popLayout">
                    {goal.achieved ? (
                      <m.span
                        key="done"
                        initial={{ scale: 0.2, opacity: 0 }}
                        animate={{ scale: 1, opacity: 1 }}
                        transition={{ type: "spring", stiffness: 420, damping: 18 }}
                        className="grid size-4 place-items-center rounded-full bg-glow-gold text-2xs text-accent-ink shadow-[0_0_12px_-2px_var(--wj-glow-gold)]"
                      >
                        <CheckIcon strokeWidth={3} />
                      </m.span>
                    ) : (
                      <m.span
                        key="todo"
                        exit={{ scale: 0.4, opacity: 0 }}
                        className="size-3.5 rounded-full border border-glow-jade/60"
                      />
                    )}
                  </AnimatePresence>
                </span>
                <span
                  className={`text-xs leading-relaxed transition-colors duration-500 ${
                    goal.achieved ? "text-ink-faint" : "text-ink-soft"
                  }`}
                >
                  {goal.description}
                  <span className="sr-only">{goal.achieved ? "（已达成）" : "（未达成）"}</span>
                </span>
              </li>
            ))}
          </m.ol>
        )}
      </AnimatePresence>
    </section>
  );
}
