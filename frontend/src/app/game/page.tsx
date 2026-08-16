"use client";

import { Suspense, useEffect } from "react";
import { useSearchParams } from "next/navigation";

import { useGameSocket } from "@/lib/ws";
import { useGameStore } from "@/stores/gameStore";
import { useWsStore } from "@/stores/wsStore";
import type { ServerMessage } from "@/lib/types";

function GameContent() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session_id");

  const setSession = useGameStore((s) => s.setSession);
  const addMessage = useGameStore((s) => s.addMessage);
  const stage = useGameStore((s) => s.stage);
  const setLastMessage = useWsStore((s) => s.setLastMessage);

  const { send, lastJsonMessage, readyState } = useGameSocket(sessionId);

  useEffect(() => {
    if (sessionId) {
      setSession(sessionId, "init");
    }
  }, [sessionId, setSession]);

  useEffect(() => {
    if (lastJsonMessage) {
      const message = lastJsonMessage as ServerMessage;
      setLastMessage(message);
      addMessage(message);
    }
  }, [lastJsonMessage, setLastMessage, addMessage]);

  return (
    <main className="flex min-h-screen flex-col bg-zinc-50 dark:bg-black">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <h1 className="font-semibold">文境 · 游戏</h1>
        <span className="text-sm text-zinc-500">
          session: {sessionId ?? "未连接"} | stage: {stage} | ws: {readyState}
        </span>
      </header>
      <div className="flex flex-1 gap-4 p-6">
        <aside className="w-56 shrink-0 rounded-lg border bg-white p-4 text-sm dark:bg-zinc-900">
          <h2 className="mb-3 font-medium">角色面板</h2>
          <p className="text-zinc-500">（骨架占位）</p>
        </aside>
        <section className="flex flex-1 flex-col gap-3">
          <div className="flex-1 rounded-lg border bg-white p-4 text-sm dark:bg-zinc-900">
            <h2 className="mb-3 font-medium">叙事面板</h2>
            <p className="text-zinc-500">（骨架占位 · 消息流将在此渲染）</p>
            <button
              onClick={() =>
                send({ type: "system_command", session_id: sessionId, content: { command: "ping" }, timestamp: Date.now() / 1000 })
              }
              className="mt-4 rounded bg-zinc-900 px-4 py-2 text-white dark:bg-zinc-50 dark:text-black"
            >
              发送测试消息
            </button>
          </div>
          <div className="rounded-lg border bg-white p-4 text-sm dark:bg-zinc-900">
            <h2 className="mb-3 font-medium">输入区域</h2>
            <p className="text-zinc-500">（骨架占位 · 三模式输入区）</p>
          </div>
          <div className="rounded-lg border bg-white p-4 text-sm dark:bg-zinc-900">
            <h2 className="mb-3 font-medium">回溯控制栏</h2>
            <p className="text-zinc-500">（骨架占位 · 进度条与回退按钮）</p>
          </div>
        </section>
      </div>
    </main>
  );
}

export default function GamePage() {
  return (
    <Suspense fallback={<p className="p-8 text-zinc-500">加载中...</p>}>
      <GameContent />
    </Suspense>
  );
}
