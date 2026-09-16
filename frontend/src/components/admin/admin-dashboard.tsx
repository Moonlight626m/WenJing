"use client";

import { useEffect, useMemo, useState } from "react";

import { FormError } from "@/components/auth/form-error";
import {
  formatApiError,
  listAdminScripts,
  listAdminUsage,
} from "@/lib/api";
import {
  SCRIPT_STATUS_LABELS,
  scriptStatusLabel,
  scriptVisibilityLabel,
  USAGE_PURPOSE_LABELS,
  usagePurposeLabel,
} from "@/lib/labels";
import type {
  ScriptStatus,
  ScriptSummary,
  UsageAggregateRow,
} from "@/lib/contracts/types";

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

const STATUS_STYLES: Record<ScriptStatus, string> = {
  draft: "bg-zinc-100 text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300",
  published:
    "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300",
  unpublished: "bg-amber-100 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
};

const selectClass =
  "rounded-lg border border-zinc-300 bg-white px-3 py-1.5 text-sm outline-none focus:border-zinc-500 dark:border-zinc-700 dark:bg-zinc-900";

function shortOrg(orgId: string): string {
  return orgId.slice(0, 8);
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
    <li className="flex items-center justify-between gap-4 rounded-lg border border-zinc-200 bg-white px-4 py-3 text-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="truncate font-medium">{script.name}</span>
          <span
            className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] ${STATUS_STYLES[script.status]}`}
          >
            {scriptStatusLabel(script.status)}
          </span>
          {script.status !== "draft" && (
            <span className="shrink-0 rounded-full bg-zinc-100 px-2 py-0.5 text-[11px] text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
              {scriptVisibilityLabel(script.visibility)}
            </span>
          )}
        </div>
        <p className="mt-0.5 truncate text-xs text-zinc-400">
          组织 {shortOrg(script.org_id)} · 作者 {script.owner_user_id.slice(0, 8)}
          {script.updated_at
            ? ` · 更新于 ${new Date(script.updated_at).toLocaleString()}`
            : ""}
        </p>
      </div>
    </li>
  );
}

function UsageRow({ row }: { row: UsageAggregateRow }) {
  return (
    <tr className="border-t border-zinc-200 text-sm dark:border-zinc-800">
      <td className="px-3 py-2">{shortOrg(row.org_id)}</td>
      <td className="px-3 py-2">{usagePurposeLabel(row.purpose)}</td>
      <td className="px-3 py-2 tabular-nums">{row.call_count}</td>
      <td className="px-3 py-2 tabular-nums">{row.prompt_tokens}</td>
      <td className="px-3 py-2 tabular-nums">{row.completion_tokens}</td>
      <td className="px-3 py-2 font-medium tabular-nums">{row.total_tokens}</td>
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
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");

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
    <main className="mx-auto flex w-full max-w-4xl flex-1 flex-col gap-8 p-6">
      <h1 className="text-2xl font-semibold tracking-tight">运营后台</h1>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-sm font-medium">
            剧本库{scripts !== null && `（${scripts.length}）`}
          </h2>
          <div className="flex gap-2">
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
        </div>
        {scriptsError && <FormError message={scriptsError} />}
        {scripts === null ? (
          <p className="text-sm text-zinc-400">加载剧本库…</p>
        ) : scripts.length === 0 ? (
          <p className="text-xs text-zinc-400">暂无剧本。</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {scripts.map((script) => (
              <ScriptRow key={script.id} script={script} />
            ))}
          </ul>
        )}
      </section>

      <section className="flex flex-col gap-3">
        <div className="flex items-center justify-between gap-4">
          <h2 className="text-sm font-medium">Token 用量</h2>
          <div className="flex gap-2">
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
            <input
              type="date"
              aria-label="起始日期"
              value={since}
              onChange={(e) => setSince(e.target.value)}
              className={selectClass}
            />
            <input
              type="date"
              aria-label="截止日期"
              value={until}
              onChange={(e) => setUntil(e.target.value)}
              className={selectClass}
            />
          </div>
        </div>
        {usageError && <FormError message={usageError} />}
        {usage === null ? (
          <p className="text-sm text-zinc-400">加载用量…</p>
        ) : usage.length === 0 ? (
          <p className="text-xs text-zinc-400">该筛选条件下暂无用量记录。</p>
        ) : (
          <div className="overflow-x-auto rounded-xl border border-zinc-200 dark:border-zinc-800">
            <table className="w-full text-left dark:bg-zinc-900">
              <thead>
                <tr className="text-xs text-zinc-400">
                  <th className="px-3 py-2 font-medium">组织</th>
                  <th className="px-3 py-2 font-medium">用途</th>
                  <th className="px-3 py-2 font-medium">调用次数</th>
                  <th className="px-3 py-2 font-medium">Prompt</th>
                  <th className="px-3 py-2 font-medium">Completion</th>
                  <th className="px-3 py-2 font-medium">总 Token</th>
                </tr>
              </thead>
              <tbody>
                {usage.map((row, index) => (
                  <UsageRow
                    key={`${row.org_id}-${row.purpose}-${index}`}
                    row={row}
                  />
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t border-zinc-300 text-sm dark:border-zinc-700">
                  <td className="px-3 py-2 text-xs text-zinc-400" colSpan={2}>
                    合计（当前筛选）
                  </td>
                  <td className="px-3 py-2 tabular-nums">{totals.calls}</td>
                  <td className="px-3 py-2 tabular-nums">{totals.prompt}</td>
                  <td className="px-3 py-2 tabular-nums">{totals.completion}</td>
                  <td className="px-3 py-2 font-medium tabular-nums">
                    {totals.total}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </section>
    </main>
  );
}
