"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { GenerationProgress } from "@/components/teacher/generation-progress";
import { ScriptPreview } from "@/components/teacher/script-preview";
import {
  deleteScript,
  formatApiError,
  getScriptDetail,
  publishScript,
  regenerateScript,
  resumeScriptGeneration,
  startScriptGeneration,
  unpublishScript,
} from "@/lib/api";
import {
  scriptStatusLabel,
  scriptVisibilityLabel,
  SCRIPT_VISIBILITY_LABELS,
} from "@/lib/labels";
import type {
  ScriptDetail,
  ScriptVisibility,
} from "@/lib/contracts/types";

const ACTION_CLASS =
  "rounded-lg border border-zinc-300 px-3 py-1.5 text-sm transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:hover:bg-zinc-800";

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
  const [directivesDraft, setDirectivesDraft] = useState("");

  const running = detail?.generation?.status === "running";
  const awaitingReview = detail?.generation?.status === "awaiting_review";
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

  async function handleResume() {
    const directives = directivesDraft
      .split("\n")
      .map((line) => line.trim())
      .filter(Boolean);
    await run("resume", async () => {
      await resumeScriptGeneration(scriptId, directives);
      setDirectivesDraft("");
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
        <GenerationProgress generation={generation} />
      )}

      {awaitingReview && (
        <section className="flex flex-col gap-3 rounded-xl border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
          <h2 className="text-sm font-medium text-amber-700 dark:text-amber-300">
            教师闸门 · 素材审阅
          </h2>
          <p className="text-xs text-amber-700/80 dark:text-amber-300/80">
            素材收集与考证已通过。可填写指导指令（自然语言，如“孔乙己的迂腐要更突出”），
            恢复后作为下游节点的额外约束；也可以不填直接恢复。
          </p>
          <textarea
            value={directivesDraft}
            onChange={(e) => setDirectivesDraft(e.target.value)}
            rows={3}
            placeholder={"每行一条指导指令，例如：\n孔乙己的迂腐要更突出"}
            className="rounded-lg border border-amber-300 bg-transparent px-3 py-2 text-sm outline-none focus:border-amber-500 dark:border-amber-800"
          />
          <div className="flex items-center gap-3">
            <button
              type="button"
              onClick={() => void handleResume()}
              disabled={busy !== null}
              className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
            >
              {busy === "resume" ? "恢复中…" : "恢复生成"}
            </button>
            <span className="text-xs text-amber-700/70 dark:text-amber-300/70">
              恢复后流水线从事件划分继续。
            </span>
          </div>
        </section>
      )}

      {scriptPackage && <ScriptPreview scriptPackage={scriptPackage} />}

      <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-sm font-medium">操作</h2>
        <div className="flex flex-wrap items-center gap-3">
          {status === "draft" && !hasPackage && !running && !awaitingReview && (
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
