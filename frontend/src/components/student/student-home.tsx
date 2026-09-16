"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import {
  formatApiError,
  listMySessions,
  listSquareScripts,
} from "@/lib/api";
import { scriptVisibilityLabel, stageLabel } from "@/lib/labels";
import { routeForStage } from "@/lib/session-cache";
import type { ScriptSummary, SessionSummary } from "@/lib/contracts/types";

function GameRow({ session }: { session: SessionSummary }) {
  const router = useRouter();
  const ended = session.stage === "ended";
  return (
    <li className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">
            {session.script_name ?? "（旧会话）"}
          </span>
          <span className="shrink-0 rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {stageLabel(session.stage)}
          </span>
        </div>
        <p className="mt-0.5 truncate text-xs text-zinc-400">
          {session.player_role ? `扮演：${session.player_role}` : "未选角"}
          {session.updated_at
            ? ` · ${new Date(session.updated_at).toLocaleString()}`
            : ""}
        </p>
      </div>
      <button
        type="button"
        onClick={() =>
          router.push(
            routeForStage(
              session.session_id,
              session.stage,
              session.player_role,
              session.script_id
            )
          )
        }
        className="shrink-0 rounded-lg bg-zinc-900 px-3 py-1.5 text-xs text-white transition-opacity hover:opacity-85 dark:bg-zinc-100 dark:text-black"
      >
        {ended ? "查看" : "继续"}
      </button>
    </li>
  );
}

function SquareCard({ script }: { script: ScriptSummary }) {
  return (
    <Link
      href={`/student/scripts/${script.id}`}
      className="flex flex-col gap-1 rounded-xl border border-zinc-200 bg-white p-4 transition-colors hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-600"
    >
      <div className="flex items-center gap-2">
        <span className="font-medium">{script.name}</span>
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          {scriptVisibilityLabel(script.visibility)}
        </span>
      </div>
      {script.description && (
        <p className="line-clamp-2 text-xs text-zinc-500 dark:text-zinc-400">
          {script.description}
        </p>
      )}
      <span className="text-[11px] text-zinc-400">
        更新于 {script.updated_at ? new Date(script.updated_at).toLocaleString() : "—"}
      </span>
    </Link>
  );
}

export function StudentHomeView() {
  const [games, setGames] = useState<SessionSummary[] | null>(null);
  const [gamesError, setGamesError] = useState<string | null>(null);
  const [square, setSquare] = useState<ScriptSummary[] | null>(null);
  const [squareError, setSquareError] = useState<string | null>(null);
  const [query, setQuery] = useState("");

  useEffect(() => {
    let active = true;
    listMySessions()
      .then((resp) => {
        if (active) setGames(resp.items);
      })
      .catch((err) => {
        if (active) {
          setGamesError(formatApiError(err));
          setGames([]);
        }
      });
    listSquareScripts()
      .then((resp) => {
        if (active) setSquare(resp.items);
      })
      .catch((err) => {
        if (active) {
          setSquareError(formatApiError(err));
          setSquare([]);
        }
      });
    return () => {
      active = false;
    };
  }, []);

  const filtered = useMemo(() => {
    const base = square ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return base;
    return base.filter(
      (script) =>
        script.name.toLowerCase().includes(q) ||
        (script.description ?? "").toLowerCase().includes(q)
    );
  }, [square, query]);

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">学生空间</h1>

      <section className="flex flex-col gap-3">
        <h2 className="text-sm font-medium">我的游戏</h2>
        {gamesError && <FormError message={gamesError} />}
        {games === null ? (
          <p className="text-sm text-zinc-400">加载中…</p>
        ) : games.length === 0 ? (
          <p className="text-xs text-zinc-400">还没有游戏。从下方剧本广场选一个开始吧。</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {games.map((session) => (
              <GameRow key={session.session_id} session={session} />
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-sm font-medium">剧本广场</h2>
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索剧本名称或简介"
            className="w-56 rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900"
          />
        </div>
        {squareError && <FormError message={squareError} />}
        {square === null ? (
          <p className="text-sm text-zinc-400">加载中…</p>
        ) : filtered.length === 0 ? (
          <p className="text-xs text-zinc-400">
            {query ? "没有匹配的剧本。" : "暂无可游玩剧本，等老师发布后出现在这里。"}
          </p>
        ) : (
          <div className="grid gap-3 sm:grid-cols-2">
            {filtered.map((script) => (
              <SquareCard key={script.id} script={script} />
            ))}
          </div>
        )}
      </section>
    </main>
  );
}
