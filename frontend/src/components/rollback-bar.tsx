"use client";

import { useState } from "react";

import { useGameStore } from "@/stores/gameStore";

/** 回溯控制栏：从活动时间线选目标 seq → 二次确认 → 提交（保留旧历史，开新分支）。 */
export function RollbackBar() {
  const messages = useGameStore((s) => s.messages);
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const pending = useGameStore((s) => s.pending);
  const submit = useGameStore((s) => s.submitCommand);
  const [target, setTarget] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);

  if (!allowedCommands.includes("rollback_to_event")) return null;

  const targets = messages
    .filter((m) => m.seq > 0 && m.text.trim().length > 0)
    .sort((a, b) => a.seq - b.seq);

  function doRollback() {
    if (target === null || pending) return;
    submit("rollback_to_event", { target_sequence: target }, `回溯到 #${target}`);
    setTarget(null);
    setConfirming(false);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-zinc-200 pt-3 text-xs dark:border-zinc-800">
      <span className="text-zinc-500 dark:text-zinc-400">回溯：</span>
      <select
        value={target ?? ""}
        onChange={(e) => {
          const v = e.target.value === "" ? null : Number(e.target.value);
          setTarget(v);
          setConfirming(false);
        }}
        className="max-w-[280px] flex-1 rounded border border-zinc-300 bg-white px-2 py-1 dark:border-zinc-700 dark:bg-zinc-900"
      >
        <option value="" disabled>
          选择回到的时间点…
        </option>
        {targets.map((m) => (
          <option key={m.key} value={m.seq}>
            #{m.seq} {m.kind === "character_speech" ? `${m.speaker ?? "角色"}：` : ""}
            {m.text.slice(0, 30)}
          </option>
        ))}
      </select>
      {target !== null && !confirming && (
        <button
          onClick={() => setConfirming(true)}
          disabled={pending !== null}
          className="rounded border border-amber-400 px-3 py-1 text-amber-700 transition-colors hover:bg-amber-50 disabled:opacity-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950/40"
        >
          回到 #{target}
        </button>
      )}
      {confirming && target !== null && (
        <>
          <span className="text-zinc-500 dark:text-zinc-400">
            确认回溯到 #{target}？将开启新分支，旧历史保留。
          </span>
          <button
            onClick={doRollback}
            disabled={pending !== null}
            className="rounded bg-amber-600 px-3 py-1 text-white transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            确认
          </button>
          <button
            onClick={() => setConfirming(false)}
            className="rounded border border-zinc-300 px-3 py-1 text-zinc-500 dark:border-zinc-700 dark:text-zinc-400"
          >
            取消
          </button>
        </>
      )}
    </div>
  );
}
