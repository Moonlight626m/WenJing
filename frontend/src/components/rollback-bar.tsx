"use client";

import { useGameStore } from "@/stores/gameStore";
import { isRollbackTarget } from "@/components/message-stream";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/field";

/**
 * 回溯控制栏：从活动时间线选目标 seq → 二次确认 → 提交（保留旧历史，开新分支）。
 *
 * 受控组件：目标与确认态由剧情回顾面板持有，消息流里每句旁的「回溯到这一句」
 * 和这里的下拉框改的是同一个目标。
 */
export function RollbackBar({
  target,
  confirming,
  onTargetChange,
  onConfirmingChange,
}: {
  target: number | null;
  confirming: boolean;
  onTargetChange: (target: number | null) => void;
  onConfirmingChange: (confirming: boolean) => void;
}) {
  const messages = useGameStore((s) => s.messages);
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const pending = useGameStore((s) => s.pending);
  const submit = useGameStore((s) => s.submitCommand);

  if (!allowedCommands.includes("rollback_to_event")) return null;

  const targets = messages.filter(isRollbackTarget).sort((a, b) => a.seq - b.seq);

  function doRollback() {
    if (target === null || pending) return;
    submit("rollback_to_event", { target_sequence: target }, `回溯到 #${target}`);
    onTargetChange(null);
    onConfirmingChange(false);
  }

  return (
    <div className="flex flex-wrap items-center gap-2 border-t border-glass-edge px-4 py-3 text-xs">
      <span className="text-ink-faint">回溯</span>
      <Select
        value={target ?? ""}
        onChange={(e) => {
          const v = e.target.value === "" ? null : Number(e.target.value);
          onTargetChange(v);
          onConfirmingChange(false);
        }}
        aria-label="选择回溯到的时间点"
        controlSize="sm"
        className="w-full min-w-0 flex-1"
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
          onClick={() => onConfirmingChange(true)}
          disabled={pending !== null}
        >
          回到 #{target}
        </Button>
      )}
      {confirming && target !== null && (
        <div className="flex w-full flex-wrap items-center gap-2">
          <span className="text-ink-faint">
            确认回到 #{target}？将开启新分支，旧历史保留。
          </span>
          <Button tone="danger" size="xs" onClick={doRollback} disabled={pending !== null}>
            确认
          </Button>
          <Button tone="quiet" size="xs" onClick={() => onConfirmingChange(false)}>
            取消
          </Button>
        </div>
      )}
    </div>
  );
}
