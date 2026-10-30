"use client";

import { useState } from "react";

import { useGameStore } from "@/stores/gameStore";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";

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
    <div className="flex flex-wrap items-center gap-2 border-t border-rule pt-3 text-xs">
      <span className="text-ink-faint">回溯</span>
      <Select
        value={target ?? ""}
        onChange={(e) => {
          const v = e.target.value === "" ? null : Number(e.target.value);
          setTarget(v);
          setConfirming(false);
        }}
        aria-label="选择回溯到的时间点"
        controlSize="sm"
        className="w-full max-w-[280px] flex-1"
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
      </Select>
      {target !== null && !confirming && (
        <Button
          tone="danger"
          size="xs"
          onClick={() => setConfirming(true)}
          disabled={pending !== null}
        >
          回到 #{target}
        </Button>
      )}
      {confirming && target !== null && (
        <>
          <span className="text-ink-faint">
            确认回到 #{target}？将开启新分支，旧历史保留。
          </span>
          <Button tone="danger" size="xs" onClick={doRollback} disabled={pending !== null}>
            确认
          </Button>
          <Button tone="quiet" size="xs" onClick={() => setConfirming(false)}>
            取消
          </Button>
        </>
      )}
    </div>
  );
}
