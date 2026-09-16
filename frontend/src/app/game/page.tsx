"use client";

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useGameChannel } from "@/lib/ws";
import { getStatus, } from "@/lib/api";
import { stageLabel } from "@/lib/labels";
import { loadRecents, upsertRecent } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import { InteractionCard } from "@/components/interaction-card";
import { MessageStream } from "@/components/message-stream";
import { RolePanel } from "@/components/role-panel";
import { RollbackBar } from "@/components/rollback-bar";
import { ToastHost } from "@/components/toast-host";

const CONNECTION_LABELS: Record<string, { text: string; className: string }> = {
  idle: { text: "未连接", className: "text-zinc-400" },
  connecting: { text: "连接中…", className: "text-amber-500" },
  connected: { text: "已连接", className: "text-emerald-600 dark:text-emerald-400" },
  reconnecting: { text: "重连中…", className: "text-amber-500 animate-pulse" },
  closed: { text: "已断开", className: "text-red-500" },
};

function GameContent() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("id");

  const stage = useGameStore((s) => s.stage);
  const messages = useGameStore((s) => s.messages);
  const characters = useGameStore((s) => s.characters);
  const playableRoles = useGameStore((s) => s.playableRoles);
  const playerRole = useGameStore((s) => s.playerRole);
  const connection = useGameStore((s) => s.connection);
  const pending = useGameStore((s) => s.pending);
  const resetSession = useGameStore((s) => s.resetSession);
  const setStatusInfo = useGameStore((s) => s.setStatusInfo);

  const push = useUiStore((s) => s.push);

  useGameChannel(sessionId);

  useEffect(() => {
    if (!sessionId) return;
    if (useGameStore.getState().sessionId !== sessionId) {
      resetSession(sessionId);
    }
  }, [sessionId, resetSession]);

  // 刷新恢复：REST 状态查询补齐头部信息（角色/阶段），并记录最近会话
  // scriptId：优先取 URL（开局/选角链路携带），否则保留 localStorage 里的旧值，
  // 避免每次游戏页刷新都把记录的剧本来源覆盖丢失。
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    getStatus(sessionId)
      .then((status) => {
        if (cancelled) return;
        setStatusInfo(status);
        const scriptParam = searchParams.get("script");
        const scriptId = scriptParam
          ? Number(scriptParam)
          : (loadRecents().find((r) => r.sessionId === sessionId)?.scriptId ??
            null);
        upsertRecent({
          sessionId,
          stage: status.stage,
          title: useGameStore.getState().scriptTitle,
          playerRole: status.selected_role,
          scriptId,
          updatedAt: new Date().toISOString(),
        });
      })
      .catch(() => {
        if (!cancelled) {
          push({ kind: "error", title: "会话状态查询失败", description: "可能不存在该会话" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, searchParams, setStatusInfo, push]);

  if (!sessionId) {
    return (
      <main className="flex flex-1 flex-col items-center justify-center gap-4 p-8">
        <p>缺少会话参数。</p>
        <Link href="/" className="text-blue-600 underline dark:text-blue-400">
          返回首页
        </Link>
        <ToastHost />
      </main>
    );
  }

  const conn = CONNECTION_LABELS[connection] ?? CONNECTION_LABELS.idle;

  return (
    <main className="mx-auto flex h-screen w-full max-w-5xl flex-col p-4">
      <header className="flex items-center justify-between border-b border-zinc-200 pb-3 dark:border-zinc-800">
        <div className="flex items-baseline gap-3">
          <h1 className="font-semibold">文境</h1>
          <span className="text-xs text-zinc-400">{sessionId.slice(0, 8)}</span>
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {stageLabel(stage)}
          </span>
          {playerRole && (
            <span className="text-xs text-emerald-600 dark:text-emerald-400">
              扮演：{playerRole}
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs">
          {pending && (
            <span className="animate-pulse text-amber-500">处理中：{pending.label}…</span>
          )}
          <span className={conn.className}>{conn.text}</span>
          <Link href="/" className="text-zinc-400 underline dark:text-zinc-500">
            首页
          </Link>
        </div>
      </header>

      <div className="flex min-h-0 flex-1 gap-4 py-4">
        <aside className="hidden w-56 shrink-0 overflow-y-auto md:block">
          <h2 className="mb-3 text-xs font-medium text-zinc-400">角色面板</h2>
          <RolePanel
            characters={characters}
            playableRoles={playableRoles}
            playerRole={playerRole}
          />
        </aside>

        <section className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
            {messages.length === 0 ? (
              <p className="text-sm text-zinc-400">等待剧情开始…</p>
            ) : (
              <MessageStream messages={messages} showSeq={process.env.NODE_ENV !== "production"} />
            )}
          </div>

          <div className="mt-3 flex flex-col gap-3">
            <InteractionCard />
            <RollbackBar />
          </div>
        </section>
      </div>
      <ToastHost />
    </main>
  );
}

export default function GamePage() {
  return (
    <Suspense fallback={<p className="p-8 text-zinc-500">加载中…</p>}>
      <GameContent />
    </Suspense>
  );
}
