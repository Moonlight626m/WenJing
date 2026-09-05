"use client";

import { useEffect, useRef } from "react";
import ReactMarkdown from "react-markdown";

import type { ChatMessage } from "@/stores/gameStore";

function ContentMessage({ message }: { message: ChatMessage }) {
  if (message.kind === "system") {
    return (
      <div className="my-2 text-center text-xs text-zinc-500 dark:text-zinc-400">
        <span className="rounded-full bg-zinc-100 px-3 py-1 dark:bg-zinc-800">
          {message.text}
        </span>
      </div>
    );
  }
  if (message.kind === "character_speech") {
    return (
      <div className="my-2 flex flex-col items-start gap-1">
        <span className="text-xs font-medium text-amber-700 dark:text-amber-400">
          {message.speaker ?? "角色"}
        </span>
        <div className="max-w-[85%] rounded-2xl rounded-tl-sm bg-amber-50 px-4 py-2 text-sm text-zinc-800 dark:bg-amber-950/40 dark:text-zinc-200">
          <ReactMarkdown>{message.text}</ReactMarkdown>
        </div>
      </div>
    );
  }
  return (
    <div className="my-3 text-sm leading-relaxed text-zinc-800 dark:text-zinc-200">
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
    <div className="flex flex-col gap-1">
      {messages.map((m) => (
        <div key={m.key} className="relative">
          {showSeq && (
            <span className="absolute top-1 -left-8 text-[10px] text-zinc-300 dark:text-zinc-600">
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
