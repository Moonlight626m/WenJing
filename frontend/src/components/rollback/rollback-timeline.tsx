"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
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
  type BranchSummary,
  type SavePoint,
  type SessionTimeline,
  type TimelineEntry,
} from "@/lib/api";
import type { AssetRef, PlayerCommand } from "@/lib/contracts/types";
import { stageLabel } from "@/lib/labels";
import { buildCommand } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";

/** 一次回溯的目标：`event_id` 是首选坐标，`sequence` 只用于展示。 */
interface RollbackTarget {
  sequence: number;
  eventId: string;
  /** 场景名或存档点标签，仅用于确认文案。 */
  label: string | null;
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

/**
 * 存档点 → 实际回溯拍。
 *
 * 服务端把 `target_event_id` 解析为「目标及之前最后一个叙事事件」，所以存档点
 * 落在台词/系统事件上时会回到更早的一拍。前端提前解析，卡片按钮与确认文案才能
 * 和回溯结果一致；找不到可回溯的叙事拍时（最新存档点、只读分支）不给按钮。
 */
function resolveSavePointTarget(
  point: SavePoint,
  entries: TimelineEntry[]
): TimelineEntry | null {
  for (let i = entries.length - 1; i >= 0; i -= 1) {
    const entry = entries[i];
    if (
      entry.kind === "narrative" &&
      entry.rollbackable &&
      entry.sequence <= point.sequence
    ) {
      return entry;
    }
  }
  return null;
}

/** 分支显示名：活动分支固定「当前分支」，旧分支按创建顺序从 1 编号。 */
function branchLabels(branches: BranchSummary[]): Map<string, string> {
  const labels = new Map<string, string>();
  let ordinal = 0;
  for (const branch of branches) {
    labels.set(
      branch.branch_id,
      branch.is_active ? "当前分支" : `旧分支 ${++ordinal}`
    );
  }
  return labels;
}

function labelForBranch(
  labels: Map<string, string>,
  branchId: string | null
): string {
  return (branchId ? labels.get(branchId) : null) ?? "旧分支";
}

/** 一幕：场景图 + 简洁描述（每拍一句）+ 台词折叠；拍上带「回到这里」。 */
function SceneCard({
  group,
  index,
  latestNarrative,
  canRollback,
  savePoints,
  onPick,
}: {
  group: TimelineGroup;
  index: number;
  latestNarrative: number | null;
  canRollback: boolean;
  savePoints: Map<string, SavePoint>;
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
              const savePoint = savePoints.get(entry.event_id);
              return (
                <li key={entry.event_id} className="border-l border-rule pl-3">
                  <p className="measure text-sm leading-relaxed text-ink-soft">
                    {entry.text}
                  </p>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <span className="font-mono text-2xs text-ink-faint">
                      #{entry.sequence}
                    </span>
                    {current && <Tag tone="accent">当前进度</Tag>}
                    {savePoint && (
                      <Tag title={savePoint.label}>存档点</Tag>
                    )}
                    {canRollback && entry.rollbackable && (
                      <Button
                        tone="outline"
                        size="xs"
                        onClick={() =>
                          onPick({
                            sequence: entry.sequence,
                            eventId: entry.event_id,
                            label: group.sceneTitle,
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
                  <li
                    key={entry.event_id}
                    className="flex flex-wrap items-baseline gap-1.5 text-ink-soft"
                  >
                    <span className="text-ink-faint">
                      {entry.speaker ?? "角色"}：
                    </span>
                    <span>{entry.text}</span>
                    {savePoints.has(entry.event_id) && (
                      <Tag title={savePoints.get(entry.event_id)?.label}>
                        存档点
                      </Tag>
                    )}
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
                  <li
                    key={entry.event_id}
                    className="flex flex-wrap items-baseline gap-1.5"
                  >
                    <span>{entry.text}</span>
                    {savePoints.has(entry.event_id) && (
                      <Tag title={savePoints.get(entry.event_id)?.label}>
                        存档点
                      </Tag>
                    )}
                  </li>
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
function NotesGroup({
  group,
  savePoints,
}: {
  group: TimelineGroup;
  savePoints: Map<string, SavePoint>;
}) {
  return (
    <li className="flex flex-col gap-1.5 border-l border-rule pl-4 text-xs text-ink-faint">
      {group.entries.map((entry) => (
        <p
          key={entry.event_id}
          className="flex flex-wrap items-baseline gap-1.5"
        >
          <span>{entry.text}</span>
          {savePoints.has(entry.event_id) && (
            <Tag title={savePoints.get(entry.event_id)?.label}>存档点</Tag>
          )}
        </p>
      ))}
    </li>
  );
}

/** 存档点卡片：一条命令结束时的快照坐标（标签已由服务端按场景/命令写好）。 */
function SavePointCard({
  point,
  target,
  isHead,
  canRollback,
  readOnly,
  onPick,
}: {
  point: SavePoint;
  /** 该存档点实际会回到的叙事拍（服务端按「目标及之前最后一个叙事事件」解析）。 */
  target: TimelineEntry | null;
  isHead: boolean;
  canRollback: boolean;
  readOnly: boolean;
  onPick: (target: RollbackTarget) => void;
}) {
  let action: ReactNode = null;
  if (isHead) {
    action = (
      <Tag tone={readOnly ? undefined : "ok"} className="mt-1 self-start">
        {readOnly ? "该线终点" : "当前进度"}
      </Tag>
    );
  } else if (canRollback) {
    action = target ? (
      <Button
        tone="outline"
        size="xs"
        className="mt-1 self-start"
        onClick={() =>
          onPick({
            sequence: target.sequence,
            eventId: target.event_id,
            label: point.label,
          })
        }
      >
        回到 #{target.sequence}
      </Button>
    ) : (
      <span className="mt-1 text-2xs text-ink-faint">不可回溯</span>
    );
  }

  return (
    <li className="flex w-52 shrink-0 flex-col gap-1 rounded-lg border border-rule bg-surface px-3 py-2">
      <div className="flex items-baseline justify-between gap-2">
        <span className="font-mono text-2xs text-ink-faint tabular-nums">
          #{point.sequence}
        </span>
        <Tag tone={point.kind === "rollback" ? "accent" : undefined}>
          {point.kind === "rollback" ? "回溯" : "进度"}
        </Tag>
      </div>
      <span className="line-clamp-2 font-serif text-sm text-ink" title={point.label}>
        {point.label}
      </span>
      {point.created_at && (
        <span className="text-2xs text-ink-faint">
          {new Date(point.created_at).toLocaleString()}
        </span>
      )}
      {action}
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
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [confirming, setConfirming] = useState<RollbackTarget | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [rollbackError, setRollbackError] = useState<string | null>(null);
  // 超时/失败重试复用同一 command_id：服务端可能已经跑完并切了分支，换新 id
  // 会在新分支上再开一条（再付一次 LLM）。换目标才换命令。
  const pendingRollback = useRef<{ eventId: string; command: PlayerCommand } | null>(
    null
  );

  useEffect(() => {
    // 每次切换分支/重试都是新的 effect：cleanup 把上一轮的 active 置否，
    // 迟到的响应直接丢弃，避免快速连点时旧分支盖掉新分支。
    // 加载/清错在触发方（分支按钮、重试）里做，effect 只在回调里落结果。
    let active = true;
    getTimeline(sessionId, viewBranch ?? undefined)
      .then((resp) => {
        if (active) {
          setTimeline(resp);
          setLoading(false);
        }
      })
      .catch((err) => {
        if (active) {
          setError(formatApiError(err));
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [sessionId, viewBranch, reloadKey]);

  const groups = useMemo(
    () => (timeline ? groupTimeline(timeline.entries) : []),
    [timeline]
  );
  const latestNarrative = useMemo(
    () =>
      timeline && !timeline.read_only
        ? latestNarrativeSequence(timeline.entries)
        : null,
    [timeline]
  );
  const branchLabelById = useMemo(
    () => (timeline ? branchLabels(timeline.branches) : new Map<string, string>()),
    [timeline]
  );
  const branches = useMemo(
    () =>
      timeline
        ? [...timeline.branches].sort(
            (a, b) => Number(b.is_active) - Number(a.is_active)
          )
        : [],
    [timeline]
  );
  const recentSavePoints = useMemo(
    () => (timeline ? [...timeline.save_points].reverse() : []),
    [timeline]
  );
  const savePointByEventId = useMemo(() => {
    const map = new Map<string, SavePoint>();
    for (const point of timeline?.save_points ?? []) {
      map.set(point.event_id, point);
    }
    return map;
  }, [timeline]);
  const sceneCount = groups.filter((g) => g.sceneKey !== null).length;
  const sceneNumbers = new Map<string, number>();
  for (const group of groups) {
    if (group.sceneKey !== null) sceneNumbers.set(group.key, sceneNumbers.size + 1);
  }
  const viewedBranch = timeline?.read_only
    ? labelForBranch(branchLabelById, timeline.branch_id)
    : null;

  function retry() {
    setLoading(true);
    setError(null);
    setReloadKey((n) => n + 1);
  }

  function pickTarget(target: RollbackTarget) {
    setRollbackError(null);
    setConfirming(target);
  }

  async function doRollback() {
    if (!confirming || submitting) return;
    if (pendingRollback.current?.eventId !== confirming.eventId) {
      pendingRollback.current = {
        eventId: confirming.eventId,
        command: buildCommand(sessionId, "rollback_to_event", {
          target_event_id: confirming.eventId,
        }),
      };
    }
    setSubmitting(true);
    setRollbackError(null);
    try {
      await submitCommandRest(sessionId, pendingRollback.current.command);
      pendingRollback.current = null;
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
      // 保留确认态就地报错：会话冲突/临时故障时可以直接重试，不用重新选拍。
      setRollbackError(formatApiError(err));
      setSubmitting(false);
    }
  }

  if (error && !timeline) {
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
            <div className="flex flex-wrap items-center gap-4">
              <Button tone="outline" size="sm" onClick={retry}>
                重试
              </Button>
              <Link href="/student" className="text-sm text-accent underline">
                去学生空间
              </Link>
            </div>
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

      {branches.length > 1 && (
        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className="text-ink-faint">分支</span>
          {branches.map((branch) => {
            // 高亮跟着**已加载的** timeline 走，而不是请求中的 viewBranch：
            // 切换失败时页面仍显示旧数据，高亮不能跑到没读到的分支上。
            const current = branch.is_active
              ? !timeline.read_only
              : branch.branch_id === timeline.branch_id;
            return (
              <button
                key={branch.branch_id}
                type="button"
                aria-pressed={current}
                aria-busy={current && loading}
                title={`分支 ${branch.branch_id} · ${branch.event_count} 个事件（含继承前缀）`}
                onClick={() => {
                  if (current) return;
                  setLoading(true);
                  setError(null);
                  setConfirming(null);
                  setRollbackError(null);
                  const next = branch.is_active ? null : branch.branch_id;
                  // 同一个目标（上次加载失败）再点一次 = 重试，state 不变不会触发 effect
                  if (next === viewBranch) retry();
                  else setViewBranch(next);
                }}
                className={`rounded-full border px-2.5 py-0.5 transition-colors disabled:opacity-60 ${
                  current
                    ? "border-accent/60 bg-accent-wash text-accent"
                    : "border-rule text-ink-soft hover:text-ink"
                }`}
              >
                {branchLabelById.get(branch.branch_id) ?? "分支"}
                <span className="ml-1.5 text-ink-faint tabular-nums">
                  {branch.event_count}
                </span>
              </button>
            );
          })}
        </div>
      )}

      {loading && (
        <div className="rounded-md border border-rule bg-sunken px-3 py-2">
          <Loading label={viewBranch ? "读取旧分支…" : "读取进度…"} />
        </div>
      )}

      {error && (
        <div
          role="alert"
          className="flex flex-wrap items-center justify-between gap-3 rounded-md border border-danger/40 bg-danger-wash px-3 py-2 text-xs text-danger"
        >
          <span className="measure">{error}</span>
          <Button tone="outline" size="xs" onClick={retry}>
            重试
          </Button>
        </div>
      )}

      {timeline.read_only ? (
        <p className="measure rounded-md border border-warn/50 bg-warn-wash px-3 py-2 text-xs text-warn">
          「{viewedBranch}」已停止推进：下面是它保留的完整进度，只读回看；
          要沿这条线继续，请在活动分支上重新选择。
        </p>
      ) : (
        !timeline.can_rollback && (
          <p className="measure rounded-md border border-warn/50 bg-warn-wash px-3 py-2 text-xs text-warn">
            {timeline.entries.length === 0
              ? "剧情还没开始，暂时没有可回溯的进度。"
              : "当前阶段不开放回溯（或已超出可回溯步数），下面是只读的进度回顾。"}
          </p>
        )
      )}

      {timeline.save_points.length > 0 && (
        <>
          <SectionHeading
            title="存档点"
            meta={`${timeline.save_points.length} 处 · 最近在前`}
          />
          <ol className="flex gap-2 overflow-x-auto pb-1 sm:flex-wrap sm:overflow-visible">
            {recentSavePoints.map((point) => (
              <SavePointCard
                key={`${point.branch_id}:${point.sequence}`}
                point={point}
                target={resolveSavePointTarget(point, timeline.entries)}
                isHead={point.sequence >= timeline.head_sequence}
                canRollback={timeline.can_rollback}
                readOnly={timeline.read_only}
                onPick={pickTarget}
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
              <NotesGroup
                key={group.key}
                group={group}
                savePoints={savePointByEventId}
              />
            ) : (
              <SceneCard
                key={group.key}
                group={group}
                index={sceneNumbers.get(group.key) ?? index + 1}
                latestNarrative={latestNarrative}
                canRollback={timeline.can_rollback}
                savePoints={savePointByEventId}
                onPick={pickTarget}
              />
            )
          )}
        </ol>
      )}

      {confirming && (
        <div
          role="group"
          aria-label="回溯确认"
          className="sticky bottom-4 z-10 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/40 bg-surface px-4 py-3 shadow-lg"
        >
          <div className="flex min-w-0 flex-col gap-1">
            <span className="measure text-sm text-ink">
              确认回到 #{confirming.sequence}
              {confirming.label ? `（${confirming.label}）` : ""}？
            </span>
            <span className="measure text-xs text-ink-faint">
              该拍之后的进度会被放弃，旧分支保留可审计。
            </span>
            {rollbackError && (
              <p role="alert" className="measure text-xs text-danger">
                {rollbackError}
              </p>
            )}
          </div>
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
