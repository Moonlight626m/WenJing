"use client";

import { useState } from "react";

import type { CommandKind } from "@/lib/contracts/types";
import { useGameStore } from "@/stores/gameStore";

/** 三种输入模式：options / free_input / options_with_fallback。 */
export function InteractionCard() {
  const interaction = useGameStore((s) => s.interaction);
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const pending = useGameStore((s) => s.pending);
  const connection = useGameStore((s) => s.connection);
  const submit = useGameStore((s) => s.submitCommand);
  const [freeText, setFreeText] = useState("");

  if (!interaction) return null;

  const busy = pending !== null || connection !== "connected";
  const canChoose = allowedCommands.includes("choose_option");
  const canFree = allowedCommands.includes("free_input");

  const extraCommands = allowedCommands.filter(
    (k): k is Extract<CommandKind, "enter_stage3" | "confirm_ending" | "exit_game"> =>
      k === "enter_stage3" || k === "confirm_ending" || k === "exit_game"
  );

  function sendFreeInput() {
    const text = freeText.trim();
    if (!text || busy || !canFree) return;
    submit("free_input", { text }, "自由输入");
    setFreeText("");
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50/60 p-4 dark:border-blue-900 dark:bg-blue-950/30">
      <p className="mb-3 text-sm font-medium text-zinc-800 dark:text-zinc-200">
        {interaction.prompt || "请选择你的行动"}
      </p>
      {interaction.hint && (
        <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">{interaction.hint}</p>
      )}

      {canChoose && (
        <div className="mb-3 flex flex-wrap gap-2">
          {interaction.options.map((opt) => (
            <button
              key={opt.option_id}
              disabled={busy}
              onClick={() => submit("choose_option", { option_id: opt.option_id }, `选项 ${opt.label}`)}
              className="rounded-lg border border-blue-300 bg-white px-4 py-2 text-sm transition-colors hover:bg-blue-100 disabled:opacity-50 dark:border-blue-800 dark:bg-zinc-900 dark:hover:bg-blue-950"
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}

      {canFree && (
        <div className="flex gap-2">
          <textarea
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder={interaction.options.length > 0 ? "或输入你的行动…" : "输入你的行动…"}
            rows={2}
            maxLength={2000}
            disabled={busy}
            className="flex-1 resize-none rounded-lg border border-zinc-300 bg-white px-3 py-2 text-sm outline-none focus:border-blue-400 disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-900"
          />
          <button
            onClick={sendFreeInput}
            disabled={busy || !freeText.trim()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm text-white transition-opacity hover:opacity-85 disabled:opacity-50"
          >
            发送
          </button>
        </div>
      )}

      {!canChoose && !canFree && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">等待剧情推进…</p>
      )}

      {extraCommands.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 border-t border-blue-200/60 pt-3 dark:border-blue-900/60">
          {extraCommands.map((k) => (
            <button
              key={k}
              disabled={busy}
              onClick={() => submit(k, {}, EXTRA_LABELS[k])}
              className="rounded-lg border border-zinc-300 px-3 py-1.5 text-xs text-zinc-600 transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-400 dark:hover:bg-zinc-800"
            >
              {EXTRA_LABELS[k]}
            </button>
          ))}
        </div>
      )}

      {pending && (
        <p className="mt-3 animate-pulse text-xs text-zinc-500 dark:text-zinc-400">
          正在处理：{pending.label}（真实 LLM 模式下可能需要数十秒）…
        </p>
      )}
    </div>
  );
}

const EXTRA_LABELS: Record<string, string> = {
  enter_stage3: "进入剧情续写",
  confirm_ending: "确认结局",
  exit_game: "退出游戏",
};
