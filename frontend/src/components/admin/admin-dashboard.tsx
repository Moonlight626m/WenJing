"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import { FormError } from "@/components/auth/form-error";
import { controlClass } from "@/components/ui/field";
import { PageShell, SectionHeading } from "@/components/ui/section";
import { Loading } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";
import { formatApiError, listAdminScripts, listAdminUsage } from "@/lib/api";
import {
  SCRIPT_STATUS_LABELS,
  SCRIPT_STATUS_TONES,
  scriptStatusLabel,
  scriptVisibilityLabel,
  USAGE_PURPOSE_LABELS,
  usagePurposeLabel,
} from "@/lib/labels";
import type { ScriptSummary, UsageAggregateRow } from "@/lib/contracts/types";

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部状态" },
  ...Object.entries(SCRIPT_STATUS_LABELS).map(([value, label]) => ({
    value,
    label,
  })),
];

const PURPOSE_OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "全部用途" },
  ...Object.entries(USAGE_PURPOSE_LABELS).map(([value, label]) => ({
    value,
    label,
  })),
];

const selectClass = controlClass("sm", "w-auto");
function shortOrg(orgId: string): string {
  return orgId.slice(0, 8);
}

function toYmd(date: Date): string {
  const y = date.getFullYear();
  const m = String(date.getMonth() + 1).padStart(2, "0");
  const d = String(date.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

/** 「过去 N 天」区间（含今天）。 */
function lastNDays(n: number): { since: string; until: string } {
  const until = new Date();
  const since = new Date();
  since.setDate(since.getDate() - (n - 1));
  return { since: toYmd(since), until: toYmd(until) };
}

/**
 * 日期筛选输入：原生 date input 隐藏，由可见按钮呼出
 * （点击/键盘均可打开浏览器日期选择面板，见 showPicker()）。
 */
function DateFilterInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  const openPicker = () => {
    const input = inputRef.current;
    if (!input) return;
    // showPicker 需用户手势触发；旧浏览器无此 API 时退化为聚焦。
    if (typeof input.showPicker === "function") {
      try {
        input.showPicker();
      } catch {
        input.focus();
      }
    } else {
      input.focus();
    }
  };

  return (
    <button
      type="button"
      onClick={openPicker}
      className={`relative ${selectClass} text-left ${
        value ? "text-ink" : "text-ink-faint"
      }`}
    >
      {value || label}
      <input
        ref={inputRef}
        type="date"
        aria-label={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="absolute inset-0 h-full w-full cursor-pointer opacity-0"
        tabIndex={-1}
      />
    </button>
  );
}

/** 组织筛选下拉：两个区块共享同一 state（剧本库与用量的 org 维度联动筛选）。 */
function OrgFilterSelect({
  value,
  onChange,
  options,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
  label: string;
}) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={selectClass}
    >
      <option value="">全部组织</option>
      {options.map((id) => (
        <option key={id} value={id}>
          {shortOrg(id)}
        </option>
      ))}
    </select>
  );
}

function ScriptRow({ script }: { script: ScriptSummary }) {
  return (
    <li className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 rounded-lg border border-rule bg-surface px-4 py-3">
      <div className="min-w-0">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate font-serif text-base text-ink">
            {script.name}
          </span>
          <Tag tone={SCRIPT_STATUS_TONES[script.status]}>
            {scriptStatusLabel(script.status)}
          </Tag>
          {script.status !== "draft" && (
            <Tag>{scriptVisibilityLabel(script.visibility)}</Tag>
          )}
        </div>
        <p className="mt-1 flex flex-wrap items-center gap-x-3 text-xs text-ink-faint">
          <span className="font-mono">组织 {shortOrg(script.org_id)}</span>
          <span className="font-mono">
            作者 {script.owner_user_id.slice(0, 8)}
          </span>
          {script.updated_at && (
            <span className="font-mono">
              {new Date(script.updated_at).toLocaleString()}
            </span>
          )}
        </p>
      </div>
    </li>
  );
}

function UsageRow({ row }: { row: UsageAggregateRow }) {
  return (
    <tr className="border-t border-rule text-sm">
      <td className="px-3 py-2 font-mono text-xs">{shortOrg(row.org_id)}</td>
      <td className="px-3 py-2">{usagePurposeLabel(row.purpose)}</td>
      <td className="px-3 py-2 text-right tabular-nums">{row.call_count}</td>
      <td className="px-3 py-2 text-right tabular-nums">{row.prompt_tokens}</td>
      <td className="px-3 py-2 text-right tabular-nums">
        {row.completion_tokens}
      </td>
      <td className="px-3 py-2 text-right font-medium tabular-nums">
        {row.total_tokens}
      </td>
    </tr>
  );
}

/** 运营后台只读看板（issue #25）：剧本库 + token 聚合，无任何写操作入口。 */
export function AdminDashboard() {
  const [scripts, setScripts] = useState<ScriptSummary[] | null>(null);
  const [scriptsError, setScriptsError] = useState<string | null>(null);
  const [usage, setUsage] = useState<UsageAggregateRow[] | null>(null);
  const [usageError, setUsageError] = useState<string | null>(null);

  const [orgId, setOrgId] = useState("");
  const [status, setStatus] = useState("");
  const [purpose, setPurpose] = useState("");
  // 日期筛选默认「过去 7 天」（含今天），可清空恢复不限区间。
  const [since, setSince] = useState(() => lastNDays(7).since);
  const [until, setUntil] = useState(() => lastNDays(7).until);

  useEffect(() => {
    let active = true;
    listAdminScripts({ orgId: orgId || null, status: status || null })
      .then((resp) => {
        if (active) {
          setScripts(resp.items);
          setScriptsError(null);
        }
      })
      .catch((err) => {
        if (active) {
          setScriptsError(formatApiError(err));
          setScripts([]);
        }
      });
    listAdminUsage({
      orgId: orgId || null,
      purpose: purpose || null,
      since: since || null,
      // date input 语义为「当天含入」：补当日末尾时刻，避免 00:00 截断漏掉当天记录。
      until: until ? `${until}T23:59:59` : null,
    })
      .then((resp) => {
        if (active) {
          setUsage(resp.items);
          setUsageError(null);
        }
      })
      .catch((err) => {
        if (active) {
          setUsageError(formatApiError(err));
          setUsage([]);
        }
      });
    return () => {
      active = false;
    };
  }, [orgId, status, purpose, since, until]);

  // 组织筛选下拉：从两个数据源的去重 org_id 派生（后端暂无组织列表端点）。
  const orgOptions = useMemo(() => {
    const ids = new Set<string>();
    for (const script of scripts ?? []) ids.add(script.org_id);
    for (const row of usage ?? []) ids.add(row.org_id);
    return [...ids].sort();
  }, [scripts, usage]);

  const totals = useMemo(
    () =>
      (usage ?? []).reduce(
        (acc, row) => ({
          calls: acc.calls + row.call_count,
          prompt: acc.prompt + row.prompt_tokens,
          completion: acc.completion + row.completion_tokens,
          total: acc.total + row.total_tokens,
        }),
        { calls: 0, prompt: 0, completion: 0, total: 0 }
      ),
    [usage]
  );

  return (
    <PageShell width="max-w-4xl">
      <h1 className="text-3xl text-ink">运营后台</h1>

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="剧本库"
          meta={scripts !== null ? `${scripts.length} 篇` : undefined}
          action={
            <div className="flex flex-wrap gap-2">
              <OrgFilterSelect
                label="组织筛选"
                value={orgId}
                onChange={setOrgId}
                options={orgOptions}
              />
              <select
                aria-label="状态筛选"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className={selectClass}
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          }
        />
        {scriptsError && <FormError message={scriptsError} />}
        {scripts === null ? (
          <Loading label="加载剧本库…" />
        ) : scripts.length === 0 ? (
          <p className="text-xs text-ink-faint">暂无剧本。</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {scripts.map((script) => (
              <ScriptRow key={script.id} script={script} />
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-4">
        <SectionHeading
          title="Token 用量"
          meta={usage !== null ? `${usage.length} 组` : undefined}
          action={
            <div className="flex flex-wrap gap-2">
              <OrgFilterSelect
                label="组织筛选（用量）"
                value={orgId}
                onChange={setOrgId}
                options={orgOptions}
              />
              <select
                aria-label="用途筛选"
                value={purpose}
                onChange={(e) => setPurpose(e.target.value)}
                className={selectClass}
              >
                {PURPOSE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
              <DateFilterInput label="起始日期" value={since} onChange={setSince} />
              <DateFilterInput label="截止日期" value={until} onChange={setUntil} />
            </div>
          }
        />
        {usageError && <FormError message={usageError} />}
        {usage === null ? (
          <Loading label="加载用量…" />
        ) : usage.length === 0 ? (
          <p className="text-xs text-ink-faint">该筛选条件下暂无用量记录。</p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-rule">
            <table className="w-full text-left">
              <thead className="bg-sunken">
                <tr className="text-xs text-ink-soft">
                  <th className="px-3 py-2 font-medium">组织</th>
                  <th className="px-3 py-2 font-medium">用途</th>
                  <th className="px-3 py-2 text-right font-medium">调用次数</th>
                  <th className="px-3 py-2 text-right font-medium">Prompt</th>
                  <th className="px-3 py-2 text-right font-medium">Completion</th>
                  <th className="px-3 py-2 text-right font-medium">总 Token</th>
                </tr>
              </thead>
              <tbody>
                {usage.map((row, index) => (
                  <UsageRow key={`${row.org_id}-${row.purpose}-${index}`} row={row} />
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-rule-strong bg-sunken text-sm">
                  <td className="px-3 py-2 text-xs text-ink-soft" colSpan={2}>
                    合计（当前筛选）
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{totals.calls}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{totals.prompt}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {totals.completion}
                  </td>
                  <td className="px-3 py-2 text-right font-medium tabular-nums">
                    {totals.total}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>
    </PageShell>
  );
}
