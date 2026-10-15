"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { ScriptPreview } from "@/components/teacher/script-preview";
import { Button } from "@/components/ui/button";
import { PageShell } from "@/components/ui/section";
import { Empty, Loading } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
import { formatApiError, getScriptDetail, openSession } from "@/lib/api";
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
      <PageShell width="max-w-2xl">
        <FormError message={error} />
        <Empty
          action={
            <Link href="/student" className="text-sm text-accent underline">
              ← 返回学生空间
            </Link>
          }
        >
          可能是剧本不存在、已下架或对您不可见。
        </Empty>
      </PageShell>
    );
  }

  if (!detail || !script) {
    return (
      <PageShell width="max-w-2xl">
        <Loading label="加载剧本…" />
      </PageShell>
    );
  }

  const canPlay = script.status === "published" && pkg !== null;

  return (
    <PageShell width="max-w-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/student" className="text-sm text-accent underline">
          ← 返回学生空间
        </Link>
        <Tag>{scriptVisibilityLabel(script.visibility)}</Tag>
      </div>

      <header className="flex flex-col gap-1.5 border-b border-rule pb-3">
        <h1 className="text-2xl text-ink">{script.name}</h1>
        {script.description && (
          <p className="measure text-sm text-ink-soft">{script.description}</p>
        )}
      </header>

      {pkg ? (
        <ScriptPreview scriptPackage={pkg} audience="student" />
      ) : (
        <p className="measure rounded-md border border-warn/50 bg-warn-wash px-3 py-2 text-xs text-warn">
          剧本内容暂不可用，无法开局。
        </p>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <Button
          tone="accent"
          size="md"
          onClick={handleOpen}
          disabled={!canPlay || opening}
        >
          {opening ? "开局中…" : "开始游玩"}
        </Button>
        {!canPlay && (
          <span className="text-xs text-ink-faint">
            {script.status !== "published" ? "剧本未发布，暂不可游玩" : "剧本尚未生成完成"}
          </span>
        )}
      </div>
    </PageShell>
  );
}
