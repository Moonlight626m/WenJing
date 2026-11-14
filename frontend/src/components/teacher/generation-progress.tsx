"use client";

import { useEffect, useId, useState } from "react";

import { GENERATION_NODE_LABELS } from "@/lib/labels";
import { Spinner } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
import type {
  DoubterEvent,
  DoubterIssue,
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

function nodeText(node: NodeProgress): string {
  const label = GENERATION_NODE_LABELS[node.node] ?? node.node;
  return node.detail ? `${label}：${node.detail}` : label;
}

const SEVERITY_LABEL = {
  must_fix: "必改",
  nice_to_fix: "建议",
} as const;

/** 跨轮合并的一条问题：同一问题连续打回多轮时只留一张卡片。 */
interface MergedIssue {
  issue: DoubterIssue | string;
  rounds: number[];
}

function issueKey(node: string, issue: DoubterIssue | string): string {
  if (typeof issue === "string") {
    // 历史文本按解析出的身份参与合并；解析不出（规则校验）才用全文
    const legacy = parseLegacyIssue(issue);
    if (!legacy) return `${node}|raw|${issue}`;
    return `${node}|${legacy.severity}|${legacy.category ?? ""}|${legacy.field ?? ""}`;
  }
  // 跨轮重述会改措辞：身份取「节点+严重度+类别+字段」，引文/依据/改法只作展示
  return `${node}|${issue.severity}|${issue.category}|${issue.field}`;
}

/**
 * 打回问题按轮次去重合并。
 *
 * 生产上同一个结构问题会连打三轮（预算耗尽才失败），逐轮原样列出等于把
 * 同一篇长文重复三遍。只在**不同轮次**间合并：同一轮同字段的多个问题各自
 * 成卡，避免互相覆盖；合并时以最新一轮的措辞为准。
 */
function mergeRejectIssues(events: DoubterEvent[]): MergedIssue[] {
  const merged: MergedIssue[] = [];
  const index = new Map<string, MergedIssue>();
  for (const event of events) {
    if (event.verdict !== "reject") continue;
    for (const issue of event.issues) {
      const key = issueKey(event.node, issue);
      const hit = index.get(key);
      if (hit && !hit.rounds.includes(event.round)) {
        hit.rounds.push(event.round);
        hit.issue = issue;
        continue;
      }
      const entry = { issue, rounds: [event.round] };
      if (!hit) index.set(key, entry);
      merged.push(entry);
    }
  }
  // 必改置顶（与卡片的严重度色一致），同类保持出现顺序
  return merged.sort((a, b) => severityRank(a.issue) - severityRank(b.issue));
}

function severityRank(issue: DoubterIssue | string): number {
  const severity =
    typeof issue === "string" ? parseLegacyIssue(issue)?.severity : issue.severity;
  return severity === "must_fix" ? 0 : 1;
}

/**
 * 历史落库的 issues 是 `_format_issue` 拍平的文本：
 * `[must_fix] 事件顺序 @scenes[3].beats[0]「…」依据：…建议：…`。
 *
 * 只解析**开头**的固定记号（severity 来自闭集、类别来自闭集、字段无空格），
 * 不去拆「依据/建议」正文——那部分本身含分隔符，拆不可靠。解析失败就当
 * 规则校验的纯文本（validate_replay 的结构问题恰好也是纯文本）。
 */
const LEGACY_ISSUE_PREFIX =
  /^\[(must_fix|nice_to_fix)\]\s*(人物事实|事件顺序|编造情节|篡改关键事实)?\s*@([^\s「]+?)(?=「|依据：|建议：|\s|$)\s*/;
const LEGACY_ISSUE_QUOTE = /^「([^」]*)」\s*/;

function parseLegacyIssue(text: string) {
  const match = LEGACY_ISSUE_PREFIX.exec(text);
  if (!match) return null;
  let body = text.slice(match[0].length);
  let quote = "";
  const quoted = LEGACY_ISSUE_QUOTE.exec(body);
  if (quoted) {
    quote = quoted[1];
    body = body.slice(quoted[0].length);
  }
  return {
    severity: match[1] as "must_fix" | "nice_to_fix",
    category: match[2] ?? null,
    field: match[3] ?? null,
    quote,
    body,
  };
}

/** 裁决摘要：必改/建议/规则各几条（历史字符串按可解析的开头记号归类）。 */
function eventSummary(event: DoubterEvent): string | null {
  if (event.verdict === "pass") return null;
  let must = 0;
  let nice = 0;
  let rules = 0;
  for (const issue of event.issues) {
    if (typeof issue === "string") {
      const legacy = parseLegacyIssue(issue);
      if (!legacy) {
        rules += 1;
      } else if (legacy.severity === "must_fix") {
        must += 1;
      } else {
        nice += 1;
      }
      continue;
    }
    if (issue.severity === "must_fix") must += 1;
    else nice += 1;
  }
  const parts: string[] = [];
  if (must) parts.push(`必改 ${must}`);
  if (nice) parts.push(`建议 ${nice}`);
  if (rules) parts.push(`规则 ${rules}`);
  return parts.join(" · ");
}

function SeverityTag({ severity }: { severity: "must_fix" | "nice_to_fix" }) {
  return (
    <Tag tone={severity === "must_fix" ? "danger" : "warn"}>
      {SEVERITY_LABEL[severity]}
    </Tag>
  );
}

function FieldPath({ field }: { field: string }) {
  return (
    <span
      title={field}
      className="max-w-[20rem] truncate font-mono text-2xs text-ink-faint"
    >
      {field}
    </span>
  );
}

function QuoteLine({ quote }: { quote: string }) {
  return (
    <p className="mt-1.5 border-l-2 border-rule-strong pl-2 text-xs leading-relaxed text-ink">
      「{quote}」
    </p>
  );
}

function RoundStamp({ rounds }: { rounds: number[] }) {
  return (
    <span className="ml-auto font-mono text-2xs text-ink-faint">
      第 {rounds.join("、")} 轮
    </span>
  );
}

function IssueCard({ entry }: { entry: MergedIssue }) {
  if (typeof entry.issue === "string") {
    const legacy = parseLegacyIssue(entry.issue);
    return (
      <li className="rounded-md border border-rule bg-canvas/40 p-2.5">
        <div className="flex flex-wrap items-center gap-1.5">
          {legacy ? (
            <>
              <SeverityTag severity={legacy.severity} />
              {legacy.category && <Tag tone="neutral">{legacy.category}</Tag>}
              {legacy.field && <FieldPath field={legacy.field} />}
            </>
          ) : (
            <Tag tone="neutral">规则校验</Tag>
          )}
          <RoundStamp rounds={entry.rounds} />
        </div>
        {legacy?.quote && <QuoteLine quote={legacy.quote} />}
        <p className="mt-1.5 text-xs leading-relaxed text-ink-soft">
          {legacy ? legacy.body : entry.issue}
        </p>
      </li>
    );
  }
  const issue = entry.issue;
  return (
    <li className="rounded-md border border-rule bg-canvas/40 p-2.5">
      <div className="flex flex-wrap items-center gap-1.5">
        <SeverityTag severity={issue.severity} />
        <Tag tone="neutral">{issue.category}</Tag>
        <FieldPath field={issue.field} />
        <RoundStamp rounds={entry.rounds} />
      </div>
      {issue.quote && <QuoteLine quote={issue.quote} />}
      {issue.suggestion && (
        <details className="mt-1.5 text-2xs text-ink-soft" open>
          <summary className="cursor-pointer text-ink-faint">改法</summary>
          <p className="mt-1 leading-relaxed">{issue.suggestion}</p>
        </details>
      )}
      {issue.evidence && (
        <details className="mt-1 text-2xs text-ink-faint">
          <summary className="cursor-pointer">依据</summary>
          <p className="mt-1 leading-relaxed">{issue.evidence}</p>
        </details>
      )}
    </li>
  );
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

/** 审阅留痕：节点裁决摘要 + 可展开的问题卡片（默认折叠，有内容才出现）。 */
function DoubterTimeline({ events }: { events: DoubterEvent[] }) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  if (events.length === 0) return null;
  const rejects = events.filter((e) => e.verdict === "reject");
  const issues = mergeRejectIssues(events);
  return (
    <div className="border-t border-rule pt-2">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={panelId}
        className="text-xs text-ink-soft transition-colors hover:text-ink"
      >
        <span aria-hidden>{open ? "▾" : "▸"}</span> 审阅留痕（{events.length} 条
        {rejects.length > 0 && `，打回 ${rejects.length} 次`}）
      </button>
      {open && (
        <div id={panelId} className="mt-2 flex flex-col gap-3">
          <ul className="flex flex-col gap-1.5">
            {events.map((event, index) => (
              <li key={index} className="flex flex-wrap items-center gap-2">
                <span className="font-mono text-2xs text-ink-faint">
                  第 {event.round} 轮
                </span>
                <span className="text-xs text-ink-soft">
                  {GENERATION_NODE_LABELS[event.node] ?? event.node}
                </span>
                <Tag tone={event.verdict === "pass" ? "ok" : "danger"}>
                  {event.verdict === "pass" ? "通过" : "打回"}
                </Tag>
                {eventSummary(event) && (
                  <span className="text-2xs text-ink-faint">
                    {eventSummary(event)}
                  </span>
                )}
              </li>
            ))}
          </ul>
          {issues.length > 0 && (
            <ul className="flex flex-col gap-1.5">
              {issues.map((entry, index) => (
                <IssueCard key={index} entry={entry} />
              ))}
            </ul>
          )}
        </div>
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
          <span className="text-xs break-words text-danger">{generation.error}</span>
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
          流水线已暂停，等待教师审阅（指导指令 / 恢复生成见下方）。
        </p>
      )}

      <DoubterTimeline events={generation.doubter_events} />
    </section>
  );
}
