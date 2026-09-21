"use client";

import {
  GENERATION_NODE_LABELS,
} from "@/lib/labels";
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

/** 节点状态徽章：运行中加载圈、完成绿色、打回琥珀、失败红色。 */
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
        className="inline-block h-5 w-5 animate-spin rounded-full border-2 border-blue-500 border-t-transparent"
      />
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

/** 生成 workflow 进度管线图：节点横排 + 状态徽章 + doubter 打回记录。 */
export function GenerationProgress({
  generation,
}: {
  generation: GenerationProgress;
}) {
  const paused = generation.status === "awaiting_review";
  return (
    <section className="flex flex-col gap-3 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-wrap items-center gap-2 text-sm font-medium">
        <span>{GENERATION_STATUS_TEXT[generation.status]}</span>
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

      {generation.doubter_events.length > 0 && (
        <ul className="flex flex-col gap-1 border-t border-zinc-200 pt-2 dark:border-zinc-800">
          {generation.doubter_events.map((event, index) => (
            <li key={index} className="text-xs text-zinc-500 dark:text-zinc-400">
              {doubterEventText(event)}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
