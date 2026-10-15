"use client";

import { useEffect, useState } from "react";

import { GENERATION_NODE_LABELS } from "@/lib/labels";
import { Spinner } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
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

const STATUS_TONE: Record<GenerationProgress["status"], string> = {
  idle: "text-ink-soft",
  running: "text-accent",
  awaiting_review: "text-warn",
  succeeded: "text-ok",
  failed: "text-danger",
};

function doubterEventText(event: DoubterEvent): string {
  const label = GENERATION_NODE_LABELS[event.node] ?? event.node;
  if (event.verdict === "pass") {
    return `第 ${event.round} 轮，${label} 考证通过`;
  }
  return `第 ${event.round} 轮，${label} 打回（${event.issues.join("；")}）`;
}

function nodeText(node: NodeProgress): string {
  const label = GENERATION_NODE_LABELS[node.node] ?? node.node;
  return node.detail ? `${label}：${node.detail}` : label;
}

/**
 * 节点状态：方章式小方块（与全站状态标记同一套语言），
 * 而不是一排彩色圆点——管子里的每一格都该看得出是哪一步。
 */
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
        className="relative inline-flex size-5 items-center justify-center"
      >
        {/* 外圈呼吸扩散，强调「正在跑这一步」 */}
        <span className="absolute inline-flex size-4 animate-ping rounded-sm bg-accent opacity-30" />
        <span className="inline-flex size-4 items-center justify-center rounded-sm border border-accent text-accent">
          <Spinner className="size-2.5" />
        </span>
      </span>
    );
  }
  if (status === "succeeded") {
    return (
      <span
        aria-label="已完成"
        className="flex size-5 items-center justify-center rounded-sm bg-ok text-xs leading-none font-bold text-canvas"
      >
        ✓
      </span>
    );
  }
  if (status === "rejected") {
    return (
      <span
        aria-label="被打回"
        className="flex size-5 items-center justify-center rounded-sm bg-warn text-xs leading-none font-bold text-canvas"
      >
        ↺
      </span>
    );
  }
  if (status === "failed") {
    return (
      <span
        aria-label="失败"
        className="flex size-5 items-center justify-center rounded-sm bg-danger text-xs leading-none font-bold text-canvas"
      >
        ✕
      </span>
    );
  }
  // pending：等待执行；闸门暂停时后续节点呈待审音色
  return (
    <span
      aria-label={paused ? "等待审阅" : "待执行"}
      className={`inline-block size-5 rounded-sm border ${
        paused ? "border-warn bg-warn-wash" : "border-rule-strong"
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
    <span className="font-mono text-xs text-ink-faint tabular-nums">
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
    <div className="border-t border-rule pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-xs text-ink-soft transition-colors hover:text-ink"
      >
        {open ? "▾" : "▸"} 考证记录（{events.length} 条
        {rejects.length > 0 && `，打回 ${rejects.length} 次`}）
      </button>
      {open && (
        <ul className="mt-2 flex flex-col gap-1">
          {events.map((event, index) => (
            <li key={index} className="text-xs text-ink-soft">
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
    <section className="flex flex-col gap-4 rounded-lg border border-rule bg-surface p-4">
      <div className="flex flex-wrap items-center gap-3">
        <span className={`text-sm font-medium ${STATUS_TONE[generation.status]}`}>
          {GENERATION_STATUS_TEXT[generation.status]}
        </span>
        {running && <Elapsed anchor={anchorState} running />}
        {paused && <Tag tone="warn">流水线已暂停</Tag>}
        {generation.error && (
          <span className="text-xs text-danger">{generation.error}</span>
        )}
      </div>

      <ol className="flex flex-wrap items-start gap-y-3">
        {generation.nodes.map((node, index) => (
          <li key={node.node} className="flex items-start">
            {index > 0 && (
              <span
                aria-hidden
                className="mx-1.5 mt-[9px] h-px w-4 bg-rule-strong sm:w-7"
              />
            )}
            <div className="flex w-16 flex-col items-center gap-1 text-center sm:w-20">
              <NodeBadge status={node.status} paused={paused} />
              <span className="text-2xs leading-tight text-ink-soft">
                {GENERATION_NODE_LABELS[node.node] ?? node.node}
              </span>
              {node.detail && (
                <span
                  title={nodeText(node)}
                  className="max-w-[5.5rem] truncate text-2xs text-ink-faint"
                >
                  {node.detail}
                </span>
              )}
            </div>
          </li>
        ))}
      </ol>

      {paused && (
        <p className="measure rounded-md border border-warn/50 bg-warn-wash px-3 py-2 text-xs text-warn">
          素材收集与考证已通过，等待教师审阅（指导指令 / 恢复生成见下方）。
        </p>
      )}

      <DoubterTimeline events={generation.doubter_events} />
    </section>
  );
}
