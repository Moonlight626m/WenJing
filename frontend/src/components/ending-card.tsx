"use client";

import { useState } from "react";
import Link from "next/link";
import { AnimatePresence, m } from "motion/react";

import type { ChatMessage, MessageEnding } from "@/stores/gameStore";
import { useGameStore } from "@/stores/gameStore";
import { Button, buttonClass } from "@/components/ui/button";
import { Tag } from "@/components/ui/tag";

const EASE = [0.2, 0.7, 0.2, 1] as const;

/** 从消息流里数出这一局的几个数：你说了几句、全剧多少段、回溯过几次。 */
export function endingStats(messages: ChatMessage[], playerRole: string | null) {
  let yours = 0;
  let lines = 0;
  let rollbacks = 0;
  for (const msg of messages) {
    if (msg.kind === "system") {
      if (msg.text.includes("已回溯")) rollbacks += 1;
      continue;
    }
    lines += 1;
    if (msg.kind === "character_speech" && msg.speaker === playerRole) yours += 1;
  }
  return { yours, lines, rollbacks };
}

/**
 * 结局卡的内容：一方「终」字朱印落下，下面一段话交代这一局。
 * 单独导出给 /showcase 摆样；游玩页用 {@link EndingCard} 包成浮层。
 */
export function EndingPanel({
  scriptTitle,
  playerRole,
  messages,
  ending = null,
  onReview,
  onClose,
}: {
  scriptTitle: string | null;
  playerRole: string | null;
  messages: ChatMessage[];
  /** 重演到达的具体结局（title/kind/description）；旧剧本或非重演为空 */
  ending?: MessageEnding | null;
  onReview: () => void;
  onClose?: () => void;
}) {
  const { yours, lines, rollbacks } = endingStats(messages, playerRole);

  return (
    <div className="glass glow-border relative flex w-[min(30rem,calc(100vw-2rem))] flex-col items-center rounded-3xl px-8 pt-10 pb-7 text-center">
      <m.span
        aria-hidden
        initial={{ scale: 1.8, rotate: -18, opacity: 0 }}
        animate={{ scale: 1, rotate: -6, opacity: 1 }}
        transition={{ type: "spring", stiffness: 260, damping: 16, delay: 0.25 }}
        className="grid size-20 place-items-center rounded-md bg-flag font-serif text-4xl text-canvas shadow-[0_0_40px_-8px_var(--wj-flag)]"
      >
        终
      </m.span>
      <h2 className="mt-6 font-serif text-2xl tracking-[0.2em] text-ink">
        {scriptTitle ? `《${scriptTitle}》演完了` : "这一局演完了"}
      </h2>
      {ending?.title && (
        <p className="mt-2 flex flex-wrap items-center justify-center gap-2 font-serif text-base text-ink-soft">
          <Tag
            tone={
              ending.kind === "canonical"
                ? "accent"
                : ending.kind === "distractor"
                  ? "warn"
                  : undefined
            }
          >
            {ending.kind === "canonical"
              ? "正史结局"
              : ending.kind === "alternate"
                ? "另一种结局"
                : ending.kind === "distractor"
                  ? "偏离结局"
                  : "结局"}
          </Tag>
          {ending.title}
        </p>
      )}
      {ending?.description && (
        <p className="measure mt-2 text-sm leading-relaxed text-ink-faint">
          {ending.description}
        </p>
      )}
      <p className="measure mt-3 font-serif text-base leading-[1.9] text-ink-soft">
        {playerRole && yours > 0 ? (
          <>
            你以<span className="text-flag">「{playerRole}」</span>的身份说了{" "}
            <span className="text-glow-gold tabular-nums">{yours}</span> 句话，
          </>
        ) : null}
        全剧一共 <span className="text-glow-gold tabular-nums">{lines}</span> 段
        {rollbacks > 0 ? (
          <>
            ，中途回溯过 <span className="text-glow-jade tabular-nums">{rollbacks}</span> 次
          </>
        ) : null}
        。
      </p>
      <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
        <Button tone="glow" size="sm" onClick={onReview}>
          回看全剧
        </Button>
        <Link href="/" className={buttonClass("outline", "sm")}>
          回到首页
        </Link>
        {onClose && (
          <button type="button" onClick={onClose} className={buttonClass("quiet", "sm")}>
            留在舞台
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * 结局卡：阶段进入「已结束」时浮到舞台中央。可以收起留在舞台上，
 * 或者直接打开剧情回顾从头看一遍。
 */
export function EndingCard({ onReview }: { onReview: () => void }) {
  const stage = useGameStore((s) => s.stage);
  const scriptTitle = useGameStore((s) => s.scriptTitle);
  const playerRole = useGameStore((s) => s.playerRole);
  const messages = useGameStore((s) => s.messages);
  const ending =
    [...messages].reverse().find((m) => m.ending)?.ending ?? null;
  const [dismissed, setDismissed] = useState(false);
  // 续写没有显式结局：进入 Stage3 后关闭本局不再弹结局卡（它只服务 Stage2 结局）。
  const enteredStage3 = messages.some((m) => m.stage === "stage3_extending");
  const open = stage === "ended" && !enteredStage3 && !dismissed;

  return (
    <AnimatePresence>
      {open && (
        <m.div
          key="ending"
          role="dialog"
          aria-modal="false"
          aria-label="结局"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 z-50 grid place-items-center bg-black/60 p-4 backdrop-blur-[3px]"
        >
          <m.div
            initial={{ opacity: 0, y: 24, scale: 0.96, filter: "blur(8px)" }}
            animate={{ opacity: 1, y: 0, scale: 1, filter: "blur(0px)" }}
            transition={{ duration: 0.6, ease: EASE }}
          >
            <EndingPanel
              scriptTitle={scriptTitle}
              playerRole={playerRole}
              messages={messages}
              ending={ending}
              onReview={() => {
                setDismissed(true);
                onReview();
              }}
              onClose={() => setDismissed(true)}
            />
          </m.div>
        </m.div>
      )}
    </AnimatePresence>
  );
}
