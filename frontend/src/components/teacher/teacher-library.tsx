"use client";

import { useEffect, useState } from "react";
import Link from "next/link";

import { FormError } from "@/components/auth/form-error";
import { formatApiError, listMyScripts } from "@/lib/api";
import { scriptStatusLabel, scriptVisibilityLabel } from "@/lib/labels";
import type { ScriptStatus, ScriptSummary } from "@/lib/contracts/types";

const SECTIONS: { status: ScriptStatus; hint: string }[] = [
  { status: "draft", hint: "待生成或待发布的剧本" },
  { status: "published", hint: "已进入学生剧本广场" },
  { status: "unpublished", hint: "已下架，存量世界可继续" },
];

const STATUS_STYLES: Record<ScriptStatus, string> = {
  draft: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  published:
    "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300",
  unpublished: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
};

function ScriptCard({ script }: { script: ScriptSummary }) {
  return (
    <Link
      href={`/teacher/scripts/${script.id}`}
      className="flex flex-col gap-1 rounded-xl border border-zinc-200 bg-white p-4 transition-colors hover:border-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:hover:border-zinc-600"
    >
      <div className="flex items-center gap-2">
        <span className="font-medium">{script.name}</span>
        <span
          className={`rounded-full px-2 py-0.5 text-[11px] ${STATUS_STYLES[script.status]}`}
        >
          {scriptStatusLabel(script.status)}
        </span>
        {script.status !== "draft" && (
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {scriptVisibilityLabel(script.visibility)}
          </span>
        )}
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

export function TeacherLibrary() {
  const [items, setItems] = useState<ScriptSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    let active = true;
    listMyScripts()
      .then((resp) => {
        if (!active) return;
        setItems(resp.items);
        setError(null);
      })
      .catch((err) => {
        if (!active) return;
        setError(formatApiError(err));
        setItems([]);
      });
    return () => {
      active = false;
    };
  }, [reloadToken]);

  if (error) {
    return (
      <div className="flex flex-col gap-3">
        <FormError message={error} />
        <button
          type="button"
          onClick={() => setReloadToken((n) => n + 1)}
          className="self-start rounded-lg border border-zinc-300 px-3 py-1.5 text-sm hover:bg-zinc-100 dark:border-zinc-700 dark:hover:bg-zinc-800"
        >
          重试
        </button>
      </div>
    );
  }

  if (items === null) {
    return <p className="text-sm text-zinc-400">加载剧本库…</p>;
  }

  return (
    <div className="flex flex-col gap-8">
      {items.length === 0 && (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          还没有剧本。点击右上角「新建剧本」，导入课文后即可生成。
        </p>
      )}

      {SECTIONS.map(({ status, hint }) => {
        const group = items.filter((item) => item.status === status);
        return (
          <section key={status} className="flex flex-col gap-3">
            <div className="flex items-baseline gap-2">
              <h2 className="text-sm font-medium">
                {scriptStatusLabel(status)}（{group.length}）
              </h2>
              <span className="text-xs text-zinc-400">{hint}</span>
            </div>
            {group.length === 0 ? (
              <p className="text-xs text-zinc-400">暂无</p>
            ) : (
              <div className="grid gap-3 sm:grid-cols-2">
                {group.map((script) => (
                  <ScriptCard key={script.id} script={script} />
                ))}
              </div>
            )}
          </section>
        );
      })}
    </div>
  );
}
