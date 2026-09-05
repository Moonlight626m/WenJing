"use client";

import { useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ApiError, createSession, getStatus } from "@/lib/api";
import { stageLabel } from "@/lib/labels";
import {
  getRecentsSnapshot,
  getServerRecentsSnapshot,
  removeRecent,
  routeForStage,
  subscribeRecents,
  upsertRecent,
  type SessionRecord,
} from "@/lib/session-cache";
import { useUiStore } from "@/stores/uiStore";
import { ToastHost } from "@/components/toast-host";

export default function Home() {
  const router = useRouter();
  const push = useUiStore((s) => s.push);
  const recents = useSyncExternalStore(
    subscribeRecents,
    getRecentsSnapshot,
    getServerRecentsSnapshot
  );
  const [creating, setCreating] = useState(false);

  async function handleStart() {
    setCreating(true);
    try {
      const { session_id } = await createSession();
      upsertRecent({
        sessionId: session_id,
        stage: "init",
        title: null,
        playerRole: null,
        updatedAt: new Date().toISOString(),
      });
      router.push(`/import?id=${session_id}`);
    } catch (err) {
      push({
        kind: "error",
        title: "创建会话失败",
        description: err instanceof ApiError ? err.envelope.message : String(err),
      });
    } finally {
      setCreating(false);
    }
  }

  async function handleResume(record: SessionRecord) {
    try {
      const status = await getStatus(record.sessionId);
      upsertRecent({
        sessionId: record.sessionId,
        stage: status.stage,
        title: record.title,
        playerRole: status.selected_role,
        updatedAt: new Date().toISOString(),
      });
      router.push(
        routeForStage(record.sessionId, status.stage, status.selected_role)
      );
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        removeRecent(record.sessionId);
        push({ kind: "error", title: "会话不存在", description: "已从最近列表移除" });
      } else {
        push({
          kind: "error",
          title: "恢复会话失败",
          description: err instanceof ApiError ? err.envelope.message : String(err),
        });
      }
    }
  }

  return (
    <main className="flex flex-1 flex-col items-center gap-10 bg-zinc-50 px-8 py-16 dark:bg-black">
      <div className="text-center">
        <h1 className="text-4xl font-semibold tracking-tight">文境</h1>
        <p className="mt-2 text-zinc-500 dark:text-zinc-400">
          导入一篇课文 · AI 生成剧本 · 扮演主角亲身演绎
        </p>
      </div>

      <button
        onClick={handleStart}
        disabled={creating}
        className="rounded-full bg-zinc-900 px-8 py-3 text-white transition-opacity hover:opacity-80 disabled:opacity-50 dark:bg-zinc-50 dark:text-black"
      >
        {creating ? "创建中…" : "开始新游戏"}
      </button>

      {recents.length > 0 && (
        <section className="w-full max-w-md">
          <h2 className="mb-3 text-sm font-medium text-zinc-500 dark:text-zinc-400">
            最近会话
          </h2>
          <ul className="flex flex-col gap-2">
            {recents.map((r) => (
              <li key={r.sessionId}>
                <button
                  onClick={() => handleResume(r)}
                  className="w-full rounded-lg border border-zinc-200 bg-white px-4 py-3 text-left text-sm transition-colors hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-600"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium">{r.title ?? "未命名剧本"}</span>
                    <span className="text-xs text-zinc-400">{stageLabel(r.stage)}</span>
                  </div>
                  <div className="mt-1 text-xs text-zinc-400">
                    {r.sessionId.slice(0, 8)} · {r.playerRole ? `扮演 ${r.playerRole} · ` : ""}
                    {new Date(r.updatedAt).toLocaleString()}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Link
        href="/import"
        className="text-xs text-zinc-400 underline dark:text-zinc-500"
      >
        直接进入导入页
      </Link>
      <ToastHost />
    </main>
  );
}
