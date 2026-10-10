"use client";

import { useEffect, useState } from "react";

import { GENERATION_NODE_LABELS } from "@/lib/labels";
import type {
  DoubterEvent,
  GenerationNodeStatusValue,
  GenerationProgress,
  NodeProgress,
} from "@/lib/contracts/types";

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

/** 节点状态徽章：运行中脉动圈、完成绿色、打回琥珀、失败红色。 */
function NodeBadge({
  status,
  paused,
}: {
  status: GenerationNodeStatusValue;
  paused: boolean;
}) {
  if (status === "running") {
    return (
      <span
        aria-label="进行中"
        className="relative inline-flex h-5 w-5 items-center justify-center"
      >
        {/* 外圈呼吸扩散 + 内圈实心点亮，强调「正在跑这一步」 */}
        <span className="absolute inline-flex h-5 w-5 animate-ping rounded-full bg-blue-400 opacity-25" />
        <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-blue-500 border-t-transparent" />
      </span>
    );
  }
  if (status === "succeeded") {
    return (
      <span
        aria-label="已完成"
        className="flex h-5 w-5 items-center justify-center rounded-full bg-emerald-500 text-[11px] font-bold text-white"
      >
        ✓
      </span>
    );
  }
  if (status === "rejected") {
    return (
      <span
        aria-label="被打回"
        className="flex h-5 w-5 items-center justify-center rounded-full bg-amber-500 text-[11px] font-bold text-white"
      >
        ↺
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        aria-label="失败"
        className="flex h-5 w-5 items-center justify-center rounded-full bg-red-500 text-[11px] font-bold text-white"
      >
        ✕
      </span>
    );
  }
  // pending：等待执行；闸门暂停时后续节点呈中性
  return (
    <span
      aria-label={paused ? "等待审阅" : "待执行"}
      className={`inline-block h-5 w-5 rounded-full border-2 ${
        paused
          ? "border-amber-400 bg-amber-100 dark:bg-amber-900/40"
          : "border-zinc-300 dark:border-zinc-700"
      }`}
    />
  );
}

/** 运行耗时（running 时逐秒跳动；其余状态定格）。anchor 为 null 时从 0 计。 */
function Elapsed({
  anchor,
  running,
}: {
  anchor: number | null;
  running: boolean;
}) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  if (now === null || anchor === null) return null;
  const seconds = Math.max(0, Math.floor((now - anchor) / 1000));
  const mm = Math.floor(seconds / 60);
  const ss = `${seconds % 60}`.padStart(2, "0");
  return (
    <span className="font-mono text-xs tabular-nums text-zinc-400 dark:text-zinc-500">
      {mm}:{ss}
    </span>
  );
}

/** doubter 打回/通过历史：默认折叠，有内容才有可展开项。 */
function DoubterTimeline({ events }: { events: DoubterEvent[] }) {
  const [open, setOpen] = useState(false);
  if (events.length === 0) return null;
  const rejects = events.filter((e) => e.verdict === "reject");
  return (
    <div className="border-t border-zinc-200 pt-2 dark:border-zinc-800">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-zinc-500 transition-colors hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
      >
        {open ? "▾" : "▸"} 考证记录（{events.length} 条
        {rejects.length > 0 && `，打回 ${rejects.length} 次`}）
      </button>
      {open && (
        <ul className="mt-2 flex flex-col gap-1">
          {events.map((event, index) => (
            <li key={index} className="text-xs text-zinc-500 dark:text-zinc-400">
              {doubterEventText(event)}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/** 生成 workflow 进度管线图：节点横排 + 状态徽章 + 运行耗时 + doubter 历史。 */
export function GenerationProgress({
  generation,
}: {
  generation: GenerationProgress;
}) {
  const paused = generation.status === "awaiting_review";
  const running = generation.status === "running";

  // 运行耗时基准：attempt 进度每次落库都会刷新 updated_at，直接用会重置钟面；
  // 记住运行期间见到的最早时间戳作为起始锚点——服务器时间比本地钟更稳。
  // anchor 为 null（暂无 updated_at）时 Elapsed 不显示，视下一帧快照再起跑。
  const [anchorState, setAnchorState] = useState<number | null>(null);
  const updatedAt = generation.updated_at
    ? new Date(generation.updated_at).getTime()
    : null;
  if (!running) {
    if (anchorState !== null) setAnchorState(null);
  } else if (
    updatedAt !== null &&
    (anchorState === null || updatedAt < anchorState)
  ) {
    setAnchorState(updatedAt);
  }

  return (
    <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <span className={running ? "text-blue-600 dark:text-blue-400" : undefined}>
          {GENERATION_STATUS_TEXT[generation.status]}
        </span>
        {running && <Elapsed anchor={anchorState} running />}
        {paused && (
          <span className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5 text-xs text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
            ⏸ 流水线已暂停
          </span>
        )}
        {generation.error && (
          <span className="text-xs text-red-500">{generation.error}</span>
        )}
      </div>

      <ol className="flex flex-wrap items-start gap-y-3">
        {generation.nodes.map((node, index) => (
          <li key={node.node} className="flex items-start">
            {index > 0 && (
              <span
                aria-hidden
                className="mx-1 mt-[9px] h-0.5 w-5 rounded bg-zinc-300 dark:bg-zinc-700 sm:w-8"
              />
            )}
            <div className="flex w-16 flex-col items-center gap-1 text-center sm:w-20">
              <NodeBadge status={node.status} paused={paused} />
              <span className="text-[11px] leading-tight text-zinc-600 dark:text-zinc-300">
                {GENERATION_NODE_LABELS[node.node] ?? node.node}
              </span>
              {node.detail && (
                <span
                  title={nodeText(node)}
                  className="max-w-[5.5rem] truncate text-[10px] text-zinc-400 dark:text-zinc-500"
                >
                  {node.detail}
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>

      {paused && (
        <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
          素材收集与考证已通过，等待教师审阅（指导指令 / 恢复生成见下方）。
        </p>
      )}

      <DoubterTimeline events={generation.doubter_events} />
    </section>
  );
}
