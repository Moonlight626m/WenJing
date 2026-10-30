"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { Skeleton, SkeletonCard } from "@/components/skeleton";
import { GateReviewPanel } from "@/components/teacher/gate-review-panel";
import { GenerationProgress } from "@/components/teacher/generation-progress";
import { ScriptPreview } from "@/components/teacher/script-preview";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";
import { Tag } from "@/components/ui/tag";
import {
  cancelScriptGeneration,
  deleteScript,
  formatApiError,
  getScriptDetail,
  publishScript,
  regenerateScript,
  resumeScriptGeneration,
  startScriptGeneration,
  subscribeGenerationProgress,
  unpublishScript,
} from "@/lib/api";
import {
  SCRIPT_STATUS_TONES,
  scriptStatusLabel,
  scriptVisibilityLabel,
  SCRIPT_VISIBILITY_LABELS,
} from "@/lib/labels";
import type { ScriptDetail, ScriptVisibility } from "@/lib/contracts/types";
import type { GateResumePayload } from "@/components/teacher/gate-review-panel";

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

  // 生成进行中：SSE 实时快照（每次落库即达），配慢轮询兜底（SSE 静默丢失/
  // 代理缓冲时保证最终可见；权威终态始终是 GET 详情）。
  useEffect(() => {
    if (!running) return;
    const closeStream = subscribeGenerationProgress(scriptId, (snapshot) => {
      // SSE 帧只带 generation：把它合入当前详情，整包字段保持不换
      setDetail((prev) => (prev ? { ...prev, generation: snapshot } : prev));
    });
    const timer = setInterval(() => {
      getScriptDetail(scriptId)
        .then((next) => setDetail(next))
        .catch(() => {
          // 兜底轮询的瞬时错误忽略，下一轮或手动操作会重试
        });
    }, 10000);
    return () => {
      closeStream();
      clearInterval(timer);
    };
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

  async function handleResume(payload: GateResumePayload) {
    await run("resume", async () => {
      await resumeScriptGeneration(scriptId, payload);
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

  /** 教师停止运行中的生成：任务取消 + 详情回写失败终态。 */
  async function handleCancel() {
    await run("cancel", () => cancelScriptGeneration(scriptId));
  }

  if (!detail) {
    return (
      <div className="flex flex-col gap-3">
        {error ? (
          <>
            <FormError message={error} />
            <div className="flex gap-4 text-sm">
              <button
                type="button"
                onClick={() => setReloadToken((n) => n + 1)}
                className="text-accent underline"
              >
                重试
              </button>
              <Link href="/teacher" className="text-ink-soft underline">
                返回剧本库
              </Link>
            </div>
          </>
        ) : (
          <DetailSkeleton />
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
    <div className="flex flex-col gap-8">
      <div className="flex flex-col gap-2">
        <Link href="/teacher" className="text-sm text-accent underline">
          ← 剧本库
        </Link>
        <div className="flex flex-wrap items-center gap-2.5 border-b border-rule pb-3">
          <h1 className="text-2xl text-ink">{script.name}</h1>
          {status && (
            <Tag tone={SCRIPT_STATUS_TONES[status]}>{scriptStatusLabel(status)}</Tag>
          )}
          {status !== "draft" && (
            <Tag>{scriptVisibilityLabel(script.visibility)}</Tag>
          )}
        </div>
        {script.description && (
          <p className="measure text-sm text-ink-soft">{script.description}</p>
        )}
      </div>

      <FormError message={error} />

      {generation && generation.status !== "idle" && (
        <GenerationProgress generation={generation} />
      )}

      {awaitingReview && (
        <GateReviewPanel
          key={detail.review ? detail.review.gate : "legacy"}
          scriptId={scriptId}
          review={detail.review}
          busy={busy}
          onResume={(payload) => void handleResume(payload)}
        />
      )}

      {scriptPackage && <ScriptPreview scriptPackage={scriptPackage} />}

      <section className="flex flex-col gap-4 rounded-lg border border-rule bg-surface p-4">
        <h2 className="border-b border-rule pb-2 text-sm text-ink-soft">操作</h2>
        <div className="flex flex-wrap items-center gap-3">
          {status === "draft" && !hasPackage && !running && !awaitingReview && (
            <Button
              tone="accent"
              size="sm"
              onClick={() => void run("generate", () => startScriptGeneration(scriptId))}
              disabled={busy !== null}
            >
              {busy === "generate" ? "启动中…" : "生成剧本"}
            </Button>
          )}

          {status === "draft" && hasPackage && (
            <Button
              tone="outline"
              size="sm"
              onClick={() => {
                if (window.confirm("重新生成会丢弃当前剧本内容，确定继续？")) {
                  void run("regenerate", () => regenerateScript(scriptId));
                }
              }}
              disabled={busy !== null}
            >
              {busy === "regenerate" ? "重新生成中…" : "重新生成"}
            </Button>
          )}

          {status === "draft" && (
            <Button
              tone="danger"
              size="sm"
              onClick={() => void handleDelete()}
              disabled={busy !== null}
            >
              {busy === "delete" ? "删除中…" : "删除草稿"}
            </Button>
          )}

          {status === "unpublished" && (
            <span className="measure text-sm text-ink-soft">
              已下架：不再进入学生剧本广场，存量世界可继续。
            </span>
          )}

          {canPublish && (
            <>
              <label className="flex items-center gap-2 text-sm text-ink-soft">
                <span>可见性</span>
                <span className="w-28">
                  <Select
                    value={visibility}
                    onChange={(e) => setVisibilityDraft(e.target.value as ScriptVisibility)}
                    disabled={busy !== null}
                    controlSize="sm"
                    className="w-full"
                  >
                    {(Object.keys(SCRIPT_VISIBILITY_LABELS) as ScriptVisibility[]).map(
                      (value) => (
                        <option key={value} value={value}>
                          {SCRIPT_VISIBILITY_LABELS[value]}
                        </option>
                      )
                    )}
                  </Select>
                </span>
              </label>
              <Button
                tone="accent"
                size="sm"
                onClick={() => void handlePublish()}
                disabled={busy !== null}
              >
                {publishButtonLabel(status, busy)}
              </Button>
              {status === "published" && (
                <Button
                  tone="outline"
                  size="sm"
                  onClick={() => {
                    if (window.confirm("下架后学生广场不再可见，确定下架？")) {
                      void run("unpublish", () => unpublishScript(scriptId));
                    }
                  }}
                  disabled={busy !== null}
                >
                  {busy === "unpublish" ? "下架中…" : "下架"}
                </Button>
              )}
            </>
          )}

          {status === "draft" && running && (
            <>
              <Button
                tone="danger"
                size="sm"
                onClick={() => void handleCancel()}
                disabled={busy !== null}
              >
                {busy === "cancel" ? "停止中…" : "停止生成"}
              </Button>
              <span className="measure text-sm text-ink-soft">
                生成进行中，完成后即可预览与发布；可随时停止。
              </span>
            </>
          )}
        </div>
      </section>
    </div>
  );
}

/** 详情页加载骨架：标题条 + 生成进度卡 + 操作卡（加载中即成型的版式预期）。 */
function DetailSkeleton() {
  return (
    <div className="flex flex-col gap-6" aria-label="加载剧本…" role="status">
      <div className="flex items-center gap-3">
        <Skeleton className="h-5 w-16" />
        <Skeleton className="h-6 w-48" />
        <Skeleton className="h-4 w-14" />
      </div>
      <SkeletonCard lines={2} />
      <SkeletonCard />
    </div>
  );
}
