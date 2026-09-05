"use client";

import { Suspense, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";

import { ApiError, getStatus, submitCommandRest } from "@/lib/api";
import { buildCommand } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import { ToastHost } from "@/components/toast-host";
import type { CharacterProfile } from "@/lib/contracts/types";

function RolesContent() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("id");

  const push = useUiStore((s) => s.push);
  const storeCharacters = useGameStore((s) => s.characters);
  const storeTitle = useGameStore((s) => s.scriptTitle);

  const [playableRoles, setPlayableRoles] = useState<string[]>([]);
  const [selectedRole, setSelectedRole] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!sessionId) return;
    getStatus(sessionId)
      .then((status) => {
        if (status.stage === "init" || status.stage === "stage1_creating") {
          router.replace(`/import?id=${sessionId}`);
          return;
        }
        setPlayableRoles(status.playable_roles);
        setSelectedRole(status.selected_role);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 404) {
          push({ kind: "error", title: "会话不存在，请重新创建" });
          router.replace("/");
        }
      });
  }, [sessionId, push, router]);

  const characters: CharacterProfile[] =
    storeCharacters.length > 0
      ? storeCharacters
      : playableRoles.map((name) => ({
          name,
          public_background: "（刷新后简介不可用，仅列角色名）",
          personality_traits: [],
          speech_style: null,
          is_player_playable: true,
        }));

  async function handleSelect(role: string) {
    if (!sessionId || submitting) return;
    setSubmitting(true);
    try {
      await submitCommandRest(
        sessionId,
        buildCommand(sessionId, "select_role", { role_name: role })
      );
      router.push(`/game?id=${sessionId}`);
    } catch (err) {
      push({
        kind: "error",
        title: "选角失败",
        description:
          err instanceof ApiError
            ? `${err.envelope.code}：${err.envelope.message}`
            : String(err),
      });
      setSubmitting(false);
    }
  }

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

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 p-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold">选择角色</h1>
          {storeTitle && (
            <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">剧本：{storeTitle}</p>
          )}
        </div>
        <span className="text-xs text-zinc-400">{sessionId.slice(0, 8)}</span>
      </header>

      {selectedRole && (
        <div className="rounded-lg border border-emerald-300 bg-emerald-50 px-4 py-3 text-sm dark:border-emerald-700 dark:bg-emerald-950/40">
          你已扮演：<span className="font-medium">{selectedRole}</span>
          <Link href={`/game?id=${sessionId}`} className="ml-2 text-emerald-700 underline dark:text-emerald-300">
            进入游戏 →
          </Link>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {characters.map((c) => {
          const isSelected = c.name === selectedRole;
          return (
            <div
              key={c.name}
              className={`flex items-start justify-between gap-4 rounded-xl border p-4 dark:bg-zinc-900 ${
                isSelected
                  ? "border-emerald-400 bg-emerald-50 dark:border-emerald-700 dark:bg-emerald-950/40"
                  : "border-zinc-200 bg-white dark:border-zinc-800"
              }`}
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-medium">{c.name}</span>
                  {c.is_player_playable && (
                    <span className="rounded-full bg-blue-100 px-2 py-0.5 text-[10px] text-blue-700 dark:bg-blue-900/60 dark:text-blue-300">
                      可扮演
                    </span>
                  )}
                </div>
                {c.public_background && (
                  <p className="mt-2 text-xs text-zinc-500 dark:text-zinc-400">
                    {c.public_background}
                  </p>
                )}
                {c.personality_traits.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1">
                    {c.personality_traits.map((t) => (
                      <span
                        key={t}
                        className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400"
                      >
                        {t}
                      </span>
                    ))}
                  </div>
                )}
              </div>
              <button
                onClick={() => handleSelect(c.name)}
                disabled={submitting || isSelected}
                className="shrink-0 rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-40 dark:bg-zinc-100 dark:text-black"
              >
                {isSelected ? "已选择" : submitting ? "提交中…" : "扮演此角色"}
              </button>
            </div>
          );
        })}
      </div>
      <ToastHost />
    </main>
  );
}

export default function RolesPage() {
  return (
    <Suspense fallback={<p className="p-8 text-zinc-500">加载中…</p>}>
      <RolesContent />
    </Suspense>
  );
}
