"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { ASSET_IMAGE_BG, AssetImage } from "@/components/asset-image";
import { FormError } from "@/components/auth/form-error";
import { Button, buttonClass } from "@/components/ui/button";
import { PageShell, SectionHeading } from "@/components/ui/section";
import { Empty, Loading } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
import {
  formatApiError,
  getTimeline,
  submitCommandRest,
  type SavePoint,
  type SessionTimeline,
  type TimelineEntry,
} from "@/lib/api";
import type { AssetRef } from "@/lib/contracts/types";
import { stageLabel } from "@/lib/labels";
import { buildCommand } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";

/** 一次回溯的目标：`event_id` 是首选坐标，`sequence` 只用于展示。 */
interface RollbackTarget {
  sequence: number;
  eventId: string;
  title: string | null;
}

/** 一幕（或一段无场景的系统提示）：条目按出现顺序分组，不重排。 */
interface TimelineGroup {
  key: string;
  sceneKey: string | null;
  sceneTitle: string | null;
  asset: AssetRef | null;
  entries: TimelineEntry[];
}

/**
 * 事件流 → 幕分组。
 *
 * 系统提示（阶段切换/方向/提议/回溯记录）**归属当前这一幕**：引擎每拍都会在
 * 叙事与台词之间追加 direction/proposal，若把系统事件单独成组，每一拍都会被拆出
 * 一张空场景卡。只有第一幕之前的系统提示才单独成组。
 */
function groupTimeline(entries: TimelineEntry[]): TimelineGroup[] {
  const groups: TimelineGroup[] = [];
  let order = 0;
  for (const entry of entries) {
    const last = groups[groups.length - 1];
    if (entry.kind === "system") {
      if (last) {
        last.entries.push(entry);
      } else {
        groups.push({
          key: `notes:${order++}`,
          sceneKey: null,
          sceneTitle: null,
          asset: null,
          entries: [entry],
        });
      }
      continue;
    }
    const sceneKey = entry.scene_key;
    if (last && last.sceneKey === sceneKey) {
      last.entries.push(entry);
    } else {
      groups.push({
        key: `${sceneKey ?? "notes"}:${order++}`,
        sceneKey,
        sceneTitle: entry.scene_title,
        asset: null,
        entries: [entry],
      });
    }
    // 场景图可能在后面的条目才到（运行期配图 asset_ready）→ 取最后一张非空图
    if (entry.current_asset) {
      groups[groups.length - 1].asset = entry.current_asset;
    }
    if (entry.scene_title) {
      groups[groups.length - 1].sceneTitle = entry.scene_title;
    }
  }
  return groups;
}

function latestNarrativeSequence(entries: TimelineEntry[]): number | null {
  let latest: number | null = null;
  for (const entry of entries) {
    if (entry.kind === "narrative") latest = entry.sequence;
  }
  return latest;
}

/** 一幕：场景图 + 简洁描述（每拍一句）+ 台词折叠；拍上带「回到这里」。 */
function SceneCard({
  group,
  index,
  latestNarrative,
  canRollback,
  onPick,
}: {
  group: TimelineGroup;
  index: number;
  latestNarrative: number | null;
  canRollback: boolean;
  onPick: (target: RollbackTarget) => void;
}) {
  const title = group.sceneTitle ?? "未命名场景";
  const narratives = group.entries.filter((e) => e.kind === "narrative");
  const speeches = group.entries.filter((e) => e.kind === "character_speech");
  const notes = group.entries.filter((e) => e.kind === "system");

  return (
    <li className="rounded-lg border border-rule bg-surface p-4">
      <div className="flex flex-col gap-4 sm:flex-row">
        <AssetImage
          asset={group.asset}
          alt={`场景「${title}」画面`}
          className={`aspect-video w-full shrink-0 rounded-sm sm:w-56 ${ASSET_IMAGE_BG}`}
          emptyLabel="本场暂无配图"
        />
        <div className="flex min-w-0 flex-1 flex-col gap-3">
          <div className="flex flex-wrap items-baseline gap-x-2.5 gap-y-1">
            <span className="font-mono text-2xs text-ink-faint tabular-nums">
              {String(index).padStart(2, "0")}
            </span>
            <h2 className="font-serif text-lg text-ink">{title}</h2>
            {narratives.length > 0 && (
              <Tag>{narratives.length} 拍</Tag>
            )}
          </div>

          <ol className="flex flex-col gap-2.5">
            {narratives.map((entry) => {
              const current = entry.sequence === latestNarrative;
              return (
                <li key={entry.sequence} className="border-l border-rule pl-3">
                  <p className="measure text-sm leading-relaxed text-ink-soft">
                    {entry.text}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className="font-mono text-2xs text-ink-faint">
                      #{entry.sequence}
                    </span>
                    {current && <Tag tone="accent">当前进度</Tag>}
                    {canRollback && entry.rollbackable && (
                      <Button
                        tone="outline"
                        size="xs"
                        onClick={() =>
                          onPick({
                            sequence: entry.sequence,
                            eventId: entry.event_id,
                            title: group.sceneTitle,
                          })
                        }
                      >
                        回到 #{entry.sequence}
                      </Button>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>

          {narratives.length === 0 && (
            <p className="text-sm text-ink-faint">这一幕没有叙事节拍。</p>
          )}

          {speeches.length > 0 && (
            <details className="text-xs text-ink-faint">
              <summary className="cursor-pointer select-none">
                在场角色的 {speeches.length} 句台词
              </summary>
              <ul className="mt-1.5 flex flex-col gap-1.5">
                {speeches.map((entry) => (
                  <li key={entry.sequence} className="text-ink-soft">
                    <span className="text-ink-faint">
                      {entry.speaker ?? "角色"}：
                    </span>
                    {entry.text}
                  </li>
                ))}
              </ul>
            </details>
          )}

          {notes.length > 0 && (
            <details className="text-xs text-ink-faint">
              <summary className="cursor-pointer select-none">
                过程提示（{notes.length}）
              </summary>
              <ul className="mt-1.5 flex flex-col gap-1">
                {notes.map((entry) => (
                  <li key={entry.sequence}>{entry.text}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      </div>
    </li>
  );
}

/** 第一幕之前的系统提示（阶段切换等）：按行列出，不参与场景卡。 */
function NotesGroup({ group }: { group: TimelineGroup }) {
  return (
    <li className="flex flex-col gap-1.5 border-l border-rule pl-4 text-xs text-ink-faint">
      {group.entries.map((entry) => (
        <p key={entry.sequence}>{entry.text}</p>
      ))}
    </li>
  );
}

/** 存档点卡片：一条命令结束时的快照坐标（标签已由服务端按场景/命令写好）。 */
function SavePointCard({
  point,
  canRollback,
  onPick,
}: {
  point: SavePoint;
  canRollback: boolean;
  onPick: (target: RollbackTarget) => void;
}) {
  return (
    <li className="flex min-w-52 flex-col gap-1 rounded-lg border border-rule bg-surface px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-2xs text-ink-faint tabular-nums">
          #{point.sequence}
        </span>
        <Tag tone={point.kind === "rollback" ? "accent" : undefined}>
          {point.kind === "rollback" ? "回溯" : "进度"}
        </Tag>
      </div>
      <span className="truncate font-serif text-sm text-ink" title={point.label}>
        {point.label}
      </span>
      {point.created_at && (
        <span className="text-2xs text-ink-faint">
          {new Date(point.created_at).toLocaleString()}
        </span>
      )}
      {canRollback && (
        <Button
          tone="outline"
          size="xs"
          className="mt-1 self-start"
          onClick={() =>
            onPick({
              sequence: point.sequence,
              eventId: point.event_id,
              title: point.label,
            })
          }
        >
          回到这里
        </Button>
      )}
    </li>
  );
}

/**
 * 独立回溯页（/game/rollback）：呈现**已经发生**的进度，逐拍回溯。
 *
 * 数据来自 `GET /api/sessions/{id}/timeline`（分支事件投影）——剧本包里尚未
 * 演到的场景不在事件流里，因此不会被提前显示。回溯后旧分支不会被删除：
 * `branches` 里可以切过去只读回看，活动分支继续玩。
 */
export function RollbackTimeline({ sessionId }: { sessionId: string }) {
  const router = useRouter();
  const push = useUiStore((s) => s.push);

  const [timeline, setTimeline] = useState<SessionTimeline | null>(null);
  const [viewBranch, setViewBranch] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<RollbackTarget | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    getTimeline(sessionId, viewBranch ?? undefined)
      .then((resp) => {
        if (active) setTimeline(resp);
      })
      .catch((err) => {
        if (active) setError(formatApiError(err));
      });
    return () => {
      active = false;
    };
  }, [sessionId, viewBranch]);

  const groups = useMemo(
    () => (timeline ? groupTimeline(timeline.entries) : []),
    [timeline]
  );
  const latestNarrative = useMemo(
    () => (timeline ? latestNarrativeSequence(timeline.entries) : null),
    [timeline]
  );
  const sceneCount = groups.filter((g) => g.sceneKey !== null).length;
  const sceneNumbers = new Map<string, number>();
  for (const group of groups) {
    if (group.sceneKey !== null) sceneNumbers.set(group.key, sceneNumbers.size + 1);
  }

  async function doRollback() {
    if (!confirming || submitting) return;
    setSubmitting(true);
    try {
      await submitCommandRest(
        sessionId,
        buildCommand(sessionId, "rollback_to_event", {
          target_event_id: confirming.eventId,
        })
      );
      push({
        kind: "success",
        title: `已回到 #${confirming.sequence}`,
        description: "旧进度保留可审计，新分支从这一拍继续。",
      });
      // 回到游戏前清空本地消息与确认水位：同一会话 id 不会触发 game 页的
      // resetSession，留着旧分支的消息会让重连的 resync 从旧水位补发，
      // 既丢掉回溯记录，又把被放弃的进度继续展示出来。
      useGameStore.getState().resetSession(sessionId);
      router.push(`/game?id=${sessionId}`);
    } catch (err) {
      push({
        kind: "error",
        title: "回溯失败",
        description: formatApiError(err),
      });
      setSubmitting(false);
      setConfirming(null);
    }
  }

  if (error) {
    return (
      <PageShell>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Link href={`/game?id=${sessionId}`} className="text-sm text-accent underline">
            ← 返回游戏
          </Link>
        </div>
        <FormError message={error} />
        <Empty
          action={
            <Link href="/student" className="text-sm text-accent underline">
              去学生空间
            </Link>
          }
        >
          可能是会话不存在，或不属于当前账号。
        </Empty>
      </PageShell>
    );
  }

  if (!timeline) {
    return (
      <PageShell>
        <Loading label="读取进度…" />
      </PageShell>
    );
  }

  return (
    <PageShell>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <Link href={`/game?id=${sessionId}`} className="text-sm text-accent underline">
          ← 返回游戏
        </Link>
        <Tag>{stageLabel(timeline.stage)}</Tag>
      </div>

      <header className="flex flex-col gap-1.5 border-b border-rule pb-3">
        <h1 className="text-2xl text-ink">回溯进度</h1>
        <p className="measure text-sm text-ink-soft">
          只列出已经发生的进度；选择一拍即在该处开启新分支，旧进度保留可审计。
        </p>
      </header>

      {timeline.branches.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-ink-faint">分支</span>
          {timeline.branches.map((branch, index) => {
            const current =
              viewBranch === branch.branch_id ||
              (viewBranch === null && branch.is_active);
            return (
              <button
                key={branch.branch_id}
                type="button"
                aria-pressed={current}
                onClick={() => {
                  setConfirming(null);
                  setViewBranch(branch.is_active ? null : branch.branch_id);
                }}
                className={`rounded-full border px-2.5 py-0.5 transition-colors ${
                  current
                    ? "border-accent/60 bg-accent-wash text-accent"
                    : "border-rule text-ink-soft hover:text-ink"
                }`}
              >
                {branch.is_active ? "当前分支" : `旧分支 ${index}`}
                <span className="ml-1.5 text-ink-faint tabular-nums">
                  {branch.event_count}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {timeline.read_only && (
        <p className="measure rounded-md border border-warn/50 bg-warn-wash px-3 py-2 text-xs text-warn">
          这是回溯后保留的旧分支，只读回看；要回到这条线，请在活动分支上重新选择。
        </p>
      )}

      {!timeline.can_rollback && (
        <p className="measure rounded-md border border-warn/50 bg-warn-wash px-3 py-2 text-xs text-warn">
          {timeline.entries.length === 0
            ? "剧情还没开始，暂时没有可回溯的进度。"
            : timeline.read_only
              ? "旧分支只读：下面是它保留的完整进度。"
              : "当前阶段不开放回溯（或已超出可回溯步数），下面是只读的进度回顾。"}
        </p>
      )}

      {timeline.save_points.length > 0 && (
        <>
          <SectionHeading
            title="存档点"
            meta={`${timeline.save_points.length} 处`}
          />
          <ol className="flex flex-wrap gap-2">
            {timeline.save_points.map((point) => (
              <SavePointCard
                key={`${point.branch_id}:${point.sequence}`}
                point={point}
                canRollback={
                  timeline.can_rollback &&
                  point.sequence < timeline.head_sequence &&
                  timeline.entries.some(
                    (e) => e.rollbackable && e.sequence <= point.sequence
                  )
                }
                onPick={setConfirming}
              />
            ))}
          </ol>
        </>
      )}

      <SectionHeading
        title="已发生的幕"
        meta={`${sceneCount} 幕 · ${groups.reduce(
          (n, g) => n + g.entries.filter((e) => e.kind === "narrative").length,
          0
        )} 拍`}
      />

      {groups.length === 0 ? (
        <Empty
          action={
            <Link href={`/game?id=${sessionId}`} className={buttonClass("accent", "sm")}>
              回到游戏
            </Link>
          }
        >
          还没有演到任何一幕，先去游戏里推进剧情吧。
        </Empty>
      ) : (
        <ol className="flex flex-col gap-4">
          {groups.map((group, index) =>
            group.sceneKey === null ? (
              <NotesGroup key={group.key} group={group} />
            ) : (
              <SceneCard
                key={group.key}
                group={group}
                index={sceneNumbers.get(group.key) ?? index + 1}
                latestNarrative={latestNarrative}
                canRollback={timeline.can_rollback}
                onPick={setConfirming}
              />
            )
          )}
        </ol>
      )}

      {confirming && (
        <div className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/40 bg-surface px-4 py-3 shadow-lg">
          <span className="measure text-sm text-ink">
            确认回到 #{confirming.sequence}
            {confirming.title ? `（${confirming.title}）` : ""}？
            将从这一拍开启新分支，已发生的旧进度保留。
          </span>
          <div className="flex items-center gap-2">
            <Button
              tone="danger"
              size="sm"
              onClick={doRollback}
              disabled={submitting}
            >
              {submitting ? "回溯中…" : "确认回溯"}
            </Button>
            <Button
              tone="quiet"
              size="sm"
              onClick={() => setConfirming(null)}
              disabled={submitting}
            >
              取消
            </Button>
          </div>
        </div>
      )}
    </PageShell>
  );
}
