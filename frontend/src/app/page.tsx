"use client";

import { useState } from "react";
import Link from "next/link";

import { createSession } from "@/lib/api";
import { useGameStore } from "@/stores/gameStore";

export default function Home() {
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const setSession = useGameStore((s) => s.setSession);

  async function handleStart() {
    setLoading(true);
    try {
      const { session_id, stage } = await createSession();
      setSession(session_id, stage);
      setSessionId(session_id);
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex flex-1 flex-col items-center justify-center gap-8 bg-zinc-50 px-8 dark:bg-black">
      <h1 className="text-4xl font-semibold tracking-tight">文境</h1>
      <p className="max-w-md text-center text-lg text-zinc-600 dark:text-zinc-400">
        语文课文情景演绎 · multi-agent 角色扮演
      </p>
      <button
        onClick={handleStart}
        disabled={loading}
        className="rounded-full bg-zinc-900 px-8 py-3 text-white transition-opacity hover:opacity-80 disabled:opacity-50 dark:bg-zinc-50 dark:text-black"
      >
        {loading ? "创建中..." : "开始游戏"}
      </button>
      {sessionId && (
        <Link
          href={`/game?session_id=${sessionId}`}
          className="text-blue-600 underline dark:text-blue-400"
        >
          进入游戏 (session: {sessionId})
        </Link>
      )}
    </main>
  );
}
