"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { ScriptPreview } from "@/components/teacher/script-preview";
import {
  formatApiError,
  getScriptDetail,
  openSession,
} from "@/lib/api";
import { scriptVisibilityLabel } from "@/lib/labels";
import { routeForStage, upsertRecent } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import type { ScriptDetail } from "@/lib/contracts/types";

/** 学生视角剧本详情：浏览剧本包并开局（POST /api/sessions {script_id}）。 */
export function StudentScriptDetail({ scriptId }: { scriptId: number }) {
  const router = useRouter();
  const push = useUiStore((s) => s.push);
  const setScriptInfo = useGameStore((s) => s.setScriptInfo);

  const [detail, setDetail] = useState<ScriptDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    let active = true;
    getScriptDetail(scriptId)
      .then((resp) => {
        if (active) setDetail(resp);
      })
      .catch((err) => {
        if (active) setError(formatApiError(err));
      });
    return () => {
      active = false;
    };
  }, [scriptId]);

  const script = detail?.script;
  const pkg = detail?.package;

  async function handleOpen() {
    if (!script || opening) return;
    setOpening(true);
    setError(null);
    try {
      const status = await openSession(script.id);
      if (pkg) setScriptInfo(pkg);
      const title = pkg?.title ?? script.name;
      upsertRecent({
        sessionId: status.session_id,
        stage: status.stage,
        title,
        playerRole: status.selected_role,
        scriptId: script.id,
        updatedAt: new Date().toISOString(),
      });
      router.push(
        routeForStage(
          status.session_id,
          status.stage,
          status.selected_role,
          script.id
        )
      );
    } catch (err) {
      push({
        kind: "error",
        title: "开局失败",
        description: formatApiError(err),
      });
      setOpening(false);
    }
  }

  if (error) {
    return (
      <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-4 p-6">
        <FormError message={error} />
        <p className="text-xs text-zinc-400">
          可能是剧本不存在、已下架或对您不可见。
        </p>
        <Link href="/student" className="text-sm text-blue-600 underline dark:text-blue-400">
          ← 返回学生空间
        </Link>
      </main>
    );
  }

  if (!detail || !script) {
    return (
      <main className="mx-auto w-full max-w-2xl flex-1 p-6">
        <p className="text-sm text-zinc-400">加载剧本…</p>
      </main>
    );
  }

  const canPlay = script.status === "published" && pkg !== null;

  return (
    <main className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 p-6">
      <div className="flex items-center justify-between">
        <Link href="/student" className="text-sm text-blue-600 underline dark:text-blue-400">
          ← 返回学生空间
        </Link>
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          {scriptVisibilityLabel(script.visibility)}
        </span>
      </div>

      <header className="flex flex-col gap-1">
        <h1 className="text-2xl font-semibold tracking-tight">{script.name}</h1>
        {script.description && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{script.description}</p>
        )}
      </header>

      {pkg ? (
        <ScriptPreview scriptPackage={pkg} />
      ) : (
        <p className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:border-amber-800 dark:bg-amber-950/50 dark:text-amber-300">
          剧本内容暂不可用，无法开局。
        </p>
      )}

      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleOpen}
          disabled={!canPlay || opening}
          className="rounded-lg bg-zinc-900 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-40 dark:bg-zinc-100 dark:text-black"
        >
          {opening ? "开局中…" : "开始游玩"}
        </button>
        {!canPlay && (
          <span className="text-xs text-zinc-400">
            {script.status !== "published" ? "剧本未发布，暂不可游玩" : "剧本尚未生成完成"}
          </span>
        )}
      </div>
    </main>
  );
}
