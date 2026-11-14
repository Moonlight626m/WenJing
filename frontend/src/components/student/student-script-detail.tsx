"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { FormError } from "@/components/auth/form-error";
import { GameRow } from "@/components/student/game-cards";
import { ScriptPreview } from "@/components/teacher/script-preview";
import { Button } from "@/components/ui/button";
import { PageShell, SectionHeading } from "@/components/ui/section";
import { Empty, Loading } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
import {
  ApiError,
  formatApiError,
  getScriptDetail,
  listMySessions,
  openSession,
} from "@/lib/api";
import { scriptVisibilityLabel } from "@/lib/labels";
import { routeForStage, upsertRecent } from "@/lib/session-cache";
import { numberSessionsByStart, sortSessionsByRecent } from "@/lib/session-groups";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import type { ScriptDetail, SessionSummary } from "@/lib/contracts/types";

/**
 * 学生视角剧本页：一页对应一部戏——上方是「我在这部戏里的各局」，
 * 下方是剧本预览与开局入口（POST /api/sessions {script_id}）。
 *
 * 剧本详情取不到但开过局时不整页报错：下架/转为不可见的剧本按可见性规则
 * 对非 owner 返回 404，但已开的剧情世界仍归学生所有、可以继续（#21 的存量世界）。
 */
export function StudentScriptDetail({ scriptId }: { scriptId: number }) {
  const router = useRouter();
  const push = useUiStore((s) => s.push);
  const setScriptInfo = useGameStore((s) => s.setScriptInfo);

  const [detail, setDetail] = useState<ScriptDetail | null>(null);
  const [detailError, setDetailError] = useState<{
    message: string;
    missing: boolean;
  } | null>(null);
  const [sessions, setSessions] = useState<SessionSummary[] | null>(null);
  const [opening, setOpening] = useState(false);

  useEffect(() => {
    let active = true;
    getScriptDetail(scriptId)
      .then((resp) => {
        if (active) setDetail(resp);
      })
      .catch((err) => {
        if (!active) return;
        setDetailError({
          message: formatApiError(err),
          // 404 = 已下架/不可见（非 owner 仅可见 published），区别于网络/服务端故障
          missing: err instanceof ApiError && err.status === 404,
        });
      });
    listMySessions()
      .then((resp) => {
        if (active) {
          setSessions(resp.items.filter((s) => s.script_id === scriptId));
        }
      })
      .catch(() => {
        // 剧情世界列表失败不阻塞剧本浏览与开局
        if (active) setSessions([]);
      });
    return () => {
      active = false;
    };
  }, [scriptId]);

  const myGames = useMemo(
    () => sortSessionsByRecent(sessions ?? []),
    [sessions]
  );
  const gameNumbers = useMemo(
    () => numberSessionsByStart(sessions ?? []),
    [sessions]
  );

  const script = detail?.script ?? null;
  const pkg = detail?.package ?? null;
  const scriptName = script?.name ?? myGames[0]?.script_name ?? "剧情世界";

  async function handleOpen() {
    if (!script || opening) return;
    setOpening(true);
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

  if (sessions === null || (detail === null && detailError === null)) {
    return (
      <PageShell width="max-w-2xl">
        <Loading label="加载剧本…" />
      </PageShell>
    );
  }

  if (!script && myGames.length === 0) {
    return (
      <PageShell width="max-w-2xl">
        <FormError message={detailError?.message ?? "剧本不存在"} />
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

  const canPlay = script?.status === "published" && pkg !== null;

  return (
    <PageShell width="max-w-2xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href="/student" className="text-sm text-accent underline">
          ← 返回学生空间
        </Link>
        {script && <Tag>{scriptVisibilityLabel(script.visibility)}</Tag>}
      </div>

      <header className="flex flex-col gap-1.5 border-b border-rule pb-3">
        <h1 className="text-2xl text-ink">{scriptName}</h1>
        {script?.description && (
          <p className="measure text-sm text-ink-soft">{script.description}</p>
        )}
      </header>

      {myGames.length > 0 && (
        <section className="flex flex-col gap-4">
          <SectionHeading title="我的剧情世界" meta={`${myGames.length} 局`} />
          <ul className="flex flex-col gap-2">
            {myGames.map((session) => (
              <GameRow
                key={session.session_id}
                session={session}
                title={`第 ${gameNumbers.get(session.session_id) ?? "?"} 局`}
              />
            ))}
          </ul>
        </section>
      )}

      {detailError ? (
        <p className="measure rounded-md border border-warn/50 bg-warn-wash px-3 py-2 text-xs text-warn">
          {detailError.missing
            ? "该剧本已下架或对您不可见；已开的剧情世界仍可继续。"
            : `剧本信息加载失败（${detailError.message}）；已开的剧情世界仍可继续。`}
        </p>
      ) : (
        <>
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
              {opening
                ? "开局中…"
                : myGames.length > 0
                  ? "再来一局"
                  : "开始游玩"}
            </Button>
            {!canPlay && (
              <span className="text-xs text-ink-faint">
                {script?.status !== "published"
                  ? "剧本未发布，暂不可游玩"
                  : "剧本尚未生成完成"}
              </span>
            )}
          </div>
        </>
      )}
    </PageShell>
  );
}
