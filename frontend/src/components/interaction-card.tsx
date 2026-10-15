"use client";

import { useState } from "react";

import type { CommandKind } from "@/lib/contracts/types";
import { useGameStore } from "@/stores/gameStore";
import { VoiceInput } from "@/components/voice-input";
import { Button, buttonClass } from "@/components/ui/button";
import { TextArea } from "@/components/ui/field";

/** 三种输入模式：options / free_input / options_with_fallback。 */
export function InteractionCard() {
  const interaction = useGameStore((s) => s.interaction);
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const pending = useGameStore((s) => s.pending);
  const connection = useGameStore((s) => s.connection);
  const submit = useGameStore((s) => s.submitCommand);
  const sessionId = useGameStore((s) => s.sessionId);
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
    <div className="rounded-lg border border-rule bg-panel px-4 py-3.5 backdrop-blur-sm">
      <p className="font-serif text-base text-ink">
        {interaction.prompt || "请选择你的行动"}
      </p>
      {interaction.hint && (
        <p className="mt-1 text-xs text-ink-faint">{interaction.hint}</p>
      )}

      {/* 抉择按整行排：选项往往是整句中文，左对齐的条目比一排药丸好读 */}
      {canChoose && (
        <div className="mt-3 flex flex-col gap-1.5">
          {interaction.options.map((opt) => (
            <button
              key={opt.option_id}
              disabled={busy}
              onClick={() =>
                submit("choose_option", { option_id: opt.option_id }, `选项 ${opt.label}`)
              }
              className="w-full rounded-md border border-rule-strong bg-surface px-3.5 py-2.5 text-left font-serif text-base text-ink transition-colors hover:border-accent hover:bg-accent-wash disabled:pointer-events-none disabled:opacity-45"
            >
              {opt.label}
            </button>
          ))}
        </div>
      )}

      {canFree && (
        <div className="mt-3 flex items-start gap-2">
          <TextArea
            value={freeText}
            onChange={(e) => setFreeText(e.target.value)}
            placeholder={
              interaction.options.length > 0 ? "或写下你的行动…" : "写下你的行动…"
            }
            rows={2}
            maxLength={2000}
            disabled={busy}
            className="w-full min-w-0 flex-1 resize-none"
          />
          <div className="flex flex-col items-stretch gap-2">
            <Button
              tone="accent"
              size="sm"
              onClick={sendFreeInput}
              disabled={busy || !freeText.trim()}
            >
              发送
            </Button>
            {/* 语音是增强输入通道：识别结果填进输入框，键盘路径不受影响（#64） */}
            <VoiceInput
              sessionId={sessionId}
              disabled={busy}
              onText={(text) => setFreeText((prev) => (prev ? `${prev}${text}` : text))}
            />
          </div>
        </div>
      )}

      {!canChoose && !canFree && (
        <p className="mt-3 text-xs text-ink-faint">等待剧情推进…</p>
      )}

      {extraCommands.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-rule pt-3">
          {extraCommands.map((k) => (
            <button
              key={k}
              disabled={busy}
              onClick={() => submit(k, {}, EXTRA_LABELS[k])}
              className={buttonClass("quiet", "xs")}
            >
              {EXTRA_LABELS[k]}
            </button>
          ))}
        </div>
      )}

      {pending && (
        <p className="mt-3 animate-pulse text-xs text-flag">
          正在推进 {pending.label}（真实 LLM 模式下可能需要数十秒）
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
