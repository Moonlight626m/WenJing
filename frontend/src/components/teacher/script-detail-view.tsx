"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { ScriptPreview } from "@/components/teacher/script-preview";
import {
  deleteScript,
  formatApiError,
  getScriptDetail,
  publishScript,
  regenerateScript,
  startScriptGeneration,
  unpublishScript,
} from "@/lib/api";
import {
  GENERATION_NODE_LABELS,
  scriptStatusLabel,
  scriptVisibilityLabel,
  SCRIPT_VISIBILITY_LABELS,
} from "@/lib/labels";
import type {
  DoubterEvent,
  GenerationNodeStatusValue,
  NodeProgress,
  ScriptDetail,
  ScriptVisibility,
} from "@/lib/contracts/types";

const PHASE_DOT: Record<GenerationNodeStatusValue, string> = {
  pending: "bg-zinc-300 dark:bg-zinc-700",
  running: "animate-pulse bg-blue-500",
  succeeded: "bg-emerald-500",
  rejected: "bg-amber-500",
  failed: "bg-red-500",
};

const ACTION_CLASS =
  "rounded-lg border border-zinc-300 px-3 py-1.5 text-sm transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800";

const GENERATION_STATUS_TEXT = {
  idle: "待生成",
  running: "生成中…",
  awaiting_review: "等待教师审阅",
  succeeded: "生成完成",
  failed: "生成失败，可重试",
} as const;

function doubterEventText(event: DoubterEvent): string {
  const label = GENERATION_NODE_LABELS[event.node] ?? event.node;
  if (event.verdict === "pass") {
    return `第 ${event.round} 轮 · ${label}：考证通过`;
  }
  return `第 ${event.round} 轮 · ${label}：打回（${event.issues.join("；")}）`;
}

function nodeText(node: NodeProgress): string {
  const label = GENERATION_NODE_LABELS[node.node] ?? node.node;
  return node.detail ? `${label} · ${node.detail}` : label;
}

/** 发布按钮文案随状态变化（published 只能改可见性，unpublished 为重新发布）。 */
function publishButtonLabel(
  status: string | null,
  busy: string | null
): string {
  if (busy === "publish") return "处理中…";
  if (status === "published") return "更新可见性";
  if (status === "unpublished") return "重新发布";
  return "发布";
}

export function ScriptDetailView({ scriptId }: { scriptId: number }) {
  const router = useRouter();
  const [detail, setDetail] = useState<ScriptDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [visibilityDraft, setVisibilityDraft] = useState<ScriptVisibility | null>(
    null
  );
  const [busy, setBusy] = useState<string | null>(null);
  const [reloadToken, setReloadToken] = useState(0);

  const running = detail?.generation?.status === "running";
  const status = detail?.script.status ?? null;
  const visibility = visibilityDraft ?? detail?.script.visibility ?? "org";

  useEffect(() => {
    let active = true;
    getScriptDetail(scriptId)
      .then((next) => {
        if (!active) return;
        setDetail(next);
        setError(null);
      })
      .catch((err) => {
        if (active) setError(formatApiError(err));
      });
    return () => {
      active = false;
    };
  }, [scriptId, reloadToken]);

  // 生成进行中：轮询详情直到 succeeded/failed
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => {
      getScriptDetail(scriptId)
        .then((next) => setDetail(next))
        .catch(() => {
          // 轮询期间的瞬时错误忽略，下一轮或手动操作会重试
        });
    }, 1500);
    return () => clearInterval(timer);
  }, [running, scriptId]);

  const refresh = useCallback(async () => {
    const next = await getScriptDetail(scriptId);
    setDetail(next);
    setError(null);
  }, [scriptId]);

  async function run(key: string, action: () => Promise<unknown>) {
    if (busy) return;
    setBusy(key);
    setError(null);
    try {
      await action();
      await refresh();
    } catch (err) {
      setError(formatApiError(err));
    } finally {
      setBusy(null);
    }
  }

  async function handlePublish() {
    await run("publish", async () => {
      await publishScript(scriptId, visibility);
      setVisibilityDraft(null);
    });
  }

  async function handleDelete() {
    if (busy || !window.confirm("删除后不可恢复，确定删除这个草稿？")) return;
    setBusy("delete");
    setError(null);
    try {
      await deleteScript(scriptId);
      router.push("/teacher");
    } catch (err) {
      setError(formatApiError(err));
      setBusy(null);
    }
  }

  if (!detail) {
    return (
      <div className="flex flex-col gap-3">
        {error ? (
          <>
            <FormError message={error} />
            <div className="flex gap-3 text-sm">
              <button
                type="button"
                onClick={() => setReloadToken((n) => n + 1)}
                className="text-blue-600 underline dark:text-blue-400"
              >
                重试
              </button>
              <Link href="/teacher" className="text-zinc-500 underline dark:text-zinc-400">
                返回剧本库
              </Link>
            </div>
          </>
        ) : (
          <p className="text-sm text-zinc-400">加载剧本…</p>
        )}
      </div>
    );
  }

  const { script, package: scriptPackage, generation } = detail;
  const hasPackage = scriptPackage !== null;
  const canPublish =
    (status === "draft" && hasPackage) ||
    status === "published" ||
    status === "unpublished";

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center gap-3">
        <Link href="/teacher" className="text-sm text-zinc-500 underline dark:text-zinc-400">
          ← 剧本库
        </Link>
        <h1 className="text-xl font-semibold">{script.name}</h1>
        <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300">
          {scriptStatusLabel(script.status)}
        </span>
        {script.status !== "draft" && (
          <span className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
            {scriptVisibilityLabel(script.visibility)}
          </span>
        )}
      </div>

      {script.description && (
        <p className="text-sm text-zinc-500 dark:text-zinc-400">{script.description}</p>
      )}

      <FormError message={error} />

      {generation && generation.status !== "idle" && (
        <section className="flex flex-col gap-2 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
          <span className="text-sm font-medium">
            {GENERATION_STATUS_TEXT[generation.status]}
            {generation.error && (
              <span className="ml-2 text-xs text-red-500">{generation.error}</span>
            )}
          </span>
          <ul className="flex flex-col gap-1">
            {generation.nodes.map((node) => (
              <li
                key={node.node}
                className="flex items-center gap-2 text-xs text-zinc-500 dark:text-zinc-400"
              >
                <span
                  className={`inline-block h-1.5 w-1.5 rounded-full ${PHASE_DOT[node.status]}`}
                />
                {nodeText(node)}
              </li>
            ))}
          </ul>
          {generation.doubter_events.length > 0 && (
            <ul className="flex flex-col gap-1 border-t border-zinc-200 pt-2 dark:border-zinc-800">
              {generation.doubter_events.map((event, index) => (
                <li
                  key={index}
                  className="text-xs text-zinc-500 dark:text-zinc-400"
                >
                  {doubterEventText(event)}
                </li>
              ))}
            </ul>
          )}
        </section>
      )}

      {scriptPackage && <ScriptPreview scriptPackage={scriptPackage} />}

      <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-sm font-medium">操作</h2>
        <div className="flex flex-wrap items-center gap-3">
          {status === "draft" && !hasPackage && !running && (
            <button
              type="button"
              onClick={() => void run("generate", () => startScriptGeneration(scriptId))}
              disabled={busy !== null}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {busy === "generate" ? "启动中…" : "生成剧本"}
            </button>
          )}

          {status === "draft" && hasPackage && (
            <button
              type="button"
              onClick={() => {
                if (window.confirm("重新生成会丢弃当前剧本内容，确定继续？")) {
                  void run("regenerate", () => regenerateScript(scriptId));
                }
              }}
              disabled={busy !== null}
              className={ACTION_CLASS}
            >
              {busy === "regenerate" ? "重新生成中…" : "重新生成"}
            </button>
          )}

          {status === "draft" && (
            <button
              type="button"
              onClick={() => void handleDelete()}
              disabled={busy !== null}
              className="rounded-lg border border-red-300 px-3 py-1.5 text-sm text-red-600 transition-colors hover:bg-red-50 disabled:opacity-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/40"
            >
              {busy === "delete" ? "删除中…" : "删除草稿"}
            </button>
          )}

          {status === "unpublished" && (
            <span className="text-sm text-zinc-500 dark:text-zinc-400">
              已下架：不再进入学生剧本广场，存量世界可继续。
            </span>
          )}

          {canPublish && (
            <>
              <label className="flex items-center gap-2 text-sm">
                <span className="text-zinc-500 dark:text-zinc-400">可见性</span>
                <select
                  value={visibility}
                  onChange={(e) => setVisibilityDraft(e.target.value as ScriptVisibility)}
                  disabled={busy !== null}
                  className="rounded-lg border border-zinc-300 bg-transparent px-2 py-1.5 text-sm outline-none focus:border-blue-400 disabled:opacity-50 dark:border-zinc-700"
                >
                  {(Object.keys(SCRIPT_VISIBILITY_LABELS) as ScriptVisibility[]).map(
                    (value) => (
                      <option key={value} value={value}>
                        {SCRIPT_VISIBILITY_LABELS[value]}
                      </option>
                    )
                  )}
                </select>
              </label>
              <button
                type="button"
                onClick={() => void handlePublish()}
                disabled={busy !== null}
                className="rounded-lg bg-emerald-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
              >
                {publishButtonLabel(status, busy)}
              </button>
              {status === "published" && (
                <button
                  type="button"
                  onClick={() => {
                    if (window.confirm("下架后学生广场不再可见，确定下架？")) {
                      void run("unpublish", () => unpublishScript(scriptId));
                    }
                  }}
                  disabled={busy !== null}
                  className={ACTION_CLASS}
                >
                  {busy === "unpublish" ? "下架中…" : "下架"}
                </button>
              )}
            </>
          )}

          {status === "draft" && running && (
            <span className="text-sm text-zinc-500 dark:text-zinc-400">
              生成进行中，完成后即可预览与发布。
            </span>
          )}
        </div>
      </section>
    </div>
  );
}
