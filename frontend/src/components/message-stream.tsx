"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";

import type { ChatMessage } from "@/stores/gameStore";
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
      <div className="my-3 flex justify-center">
        <span className="rounded-sm border border-rule bg-panel px-3 py-1 text-xs text-ink-faint">
          {message.text}
        </span>
      </div>
    );
  }

  if (message.kind === "character_speech") {
    const isOwn = playerRole !== null && message.speaker === playerRole;
    return (
      <div className="my-3 flex flex-col gap-0.5">
        <span className="flex items-center gap-1.5 text-xs font-medium text-flag">
          {message.speaker ?? "角色"}
          {isOwn && <Tag tone="flag">你</Tag>}
        </span>
        <div
          className={`max-w-[85%] ${PROSE} text-ink [text-shadow:0_1px_3px_rgba(0,0,0,0.7)]`}
        >
          <ReactMarkdown>{message.text}</ReactMarkdown>
        </div>
      </div>
    );
  }

  // 旁白：不斜体（中文合成斜体是机械倾斜），改用更轻的字色分层
  return (
    <div
      className={`my-3 ${PROSE} text-ink-soft [text-shadow:0_1px_3px_rgba(0,0,0,0.7)]`}
    >
      <ReactMarkdown>{message.text}</ReactMarkdown>
    </div>
  );
}

export function MessageStream({
  messages,
  showSeq,
  playerRole = null,
}: {
  messages: ChatMessage[];
  showSeq?: boolean;
  playerRole?: string | null;
}) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages.length]);

  return (
    <div className="flex flex-col gap-1" data-testid="message-stream">
      {messages.map((m) => (
        <div key={m.key} className="relative" data-testid="message-row">
          {showSeq && (
            <span className="absolute top-2 -left-7 font-mono text-2xs text-ink-faint">
              {m.seq}
            </span>
          )}
          <ContentMessage message={m} playerRole={playerRole} />
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
