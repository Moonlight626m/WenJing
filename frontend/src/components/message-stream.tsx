"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";

import type { ChatMessage } from "@/stores/gameStore";

function ContentMessage({ message }: { message: ChatMessage }) {
  if (message.kind === "system") {
    return (
      <div className="my-2 text-center text-xs text-white/70">
        <span className="rounded-full bg-white/10 px-3 py-1">
          {message.text}
        </span>
      </div>
    );
  }
  if (message.kind === "character_speech") {
    return (
      <div className="my-2 flex flex-col items-start gap-1">
        <span className="text-xs font-medium text-amber-300">
          {message.speaker ?? "角色"}：
        </span>
        <div className="max-w-[85%] text-sm leading-relaxed text-white/95 [text-shadow:0_1px_3px_rgba(0,0,0,0.8)]">
          <ReactMarkdown>{message.text}</ReactMarkdown>
        </div>
      </div>
    );
  }
  return (
    <div className="my-3 text-sm leading-relaxed text-white/90 [text-shadow:0_1px_3px_rgba(0,0,0,0.8)]">
      <ReactMarkdown>{message.text}</ReactMarkdown>
    </div>
  );
}

export function MessageStream({
  messages,
  showSeq,
}: {
  messages: ChatMessage[];
  showSeq?: boolean;
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
            <span className="absolute top-1 -left-8 text-[10px] text-white/30">
              {m.seq}
            </span>
          )}
          <ContentMessage message={m} />
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  );
}
