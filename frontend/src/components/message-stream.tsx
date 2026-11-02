"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";

import type { ChatMessage } from "@/stores/gameStore";
import { RewindIcon } from "@/components/ui/icons";
import { Tag } from "@/components/ui/tag";

/** 正文用宋体（课文本身就是宋体印的），行高放开到 1.85 供中文长句阅读。 */
const PROSE = "font-serif text-base leading-[1.85] [&_p]:m-0 [&_strong]:font-semibold";

function ContentMessage({
  message,
  playerRole,
}: {
  message: ChatMessage;
  playerRole: string | null;
}) {
  if (message.kind === "system") {
    return (
      <div className="animate-rise-in my-3 flex justify-center">
        <span className="rounded-full border border-glass-edge bg-glass px-3.5 py-1 text-xs text-ink-faint backdrop-blur-md">
          {message.text}
        </span>
      </div>
    );
  }

  // 名牌：一道发光短竖 + 名字。你演的角色用朱砂，其他角色用泥金
  if (message.kind === "character_speech") {
    const isOwn = playerRole !== null && message.speaker === playerRole;
    return (
      <div className="animate-rise-in my-3.5 flex flex-col gap-1">
        <span
          className={`flex items-center gap-2 text-xs font-medium ${
            isOwn ? "text-flag" : "text-glow-gold"
          }`}
        >
          <span
            aria-hidden
            className={`h-3.5 w-0.5 rounded-full ${
              isOwn
                ? "bg-flag shadow-[0_0_8px_var(--wj-flag)]"
                : "bg-glow-gold shadow-[0_0_8px_var(--wj-glow-gold)]"
            }`}
          />
          {message.speaker ?? "角色"}
          {isOwn && <Tag tone="flag">你</Tag>}
        </span>
        <div
          className={`max-w-[85%] pl-2.5 ${PROSE} text-ink [text-shadow:0_1px_3px_rgba(0,0,0,0.7)]`}
        >
          <ReactMarkdown>{message.text}</ReactMarkdown>
        </div>
      </div>
    );
  }

  // 旁白：不斜体（中文合成斜体是机械倾斜），改用更轻的字色分层
  return (
    <div
      className={`animate-rise-in my-3.5 ${PROSE} text-ink-soft [text-shadow:0_1px_3px_rgba(0,0,0,0.7)]`}
    >
      <ReactMarkdown>{message.text}</ReactMarkdown>
    </div>
  );
}

/** 能回溯到的消息：有事件序号、有正文（与回溯下拉框的候选同一口径）。 */
export function isRollbackTarget(message: ChatMessage): boolean {
  return message.seq > 0 && message.text.trim().length > 0;
}

/**
 * 消息流。给了 `onRollback` 时每条可回溯的消息右上角有一枚「回溯到这一句」，
 * 悬停或键盘聚焦时浮现（触屏上常亮）；选中的那条套一圈青碧框，和回溯栏的下拉框
 * 指向同一个目标。
 */
export function MessageStream({
  messages,
  showSeq,
  playerRole = null,
  rollbackTarget = null,
  onRollback,
}: {
  messages: ChatMessage[];
  showSeq?: boolean;
  playerRole?: string | null;
  rollbackTarget?: number | null;
  onRollback?: (seq: number) => void;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  return (
    <div className="flex flex-col gap-1" data-testid="message-stream">
      {messages.map((m) => {
        const pickable = onRollback !== undefined && isRollbackTarget(m);
        const picked = pickable && rollbackTarget === m.seq;
        return (
          <div
            key={m.key}
            className={`group relative rounded-xl pr-8 pl-2 transition-[background-color,box-shadow] duration-200 ${
              picked ? "bg-glow-jade/5 ring-1 ring-glow-jade/60" : ""
            }`}
            data-testid="message-row"
          >
            {showSeq && (
              <span className="absolute top-2 -left-7 font-mono text-2xs text-ink-faint">
                {m.seq}
              </span>
            )}
            <ContentMessage message={m} playerRole={playerRole} />
            {pickable && (
              <button
                type="button"
                onClick={() => onRollback(m.seq)}
                aria-label="回溯到这一句"
                title="回溯到这一句（开新分支，旧历史保留）"
                className="absolute top-2 right-0 grid size-7 place-items-center rounded-full border border-glass-edge bg-glass text-sm text-ink-soft opacity-0 backdrop-blur-md transition-[opacity,color,box-shadow] duration-150 group-hover:opacity-100 hover:text-glow-jade hover:shadow-[0_0_12px_-3px_var(--wj-glow-jade)] focus-visible:opacity-100 [@media(hover:none)]:opacity-70"
              >
                <RewindIcon />
              </button>
            )}
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
