"use client";

import {
  useEffect,
  useState,
  type CSSProperties,
  type KeyboardEvent,
} from "react";
import { AnimatePresence, m, type Variants } from "motion/react";

import type {
  ActiveInteraction,
  CommandKind,
  OptionItem,
} from "@/lib/contracts/types";
import { useGameStore } from "@/stores/gameStore";
import { Thinking } from "@/components/thinking";
import { VoiceInput } from "@/components/voice-input";
import { Button, buttonClass } from "@/components/ui/button";
import { SendIcon } from "@/components/ui/icons";
import { MotionRoot } from "@/components/ui/motion-root";

/** 出场缓动：先快后慢，落定时不回弹。 */
const EASE = [0.2, 0.7, 0.2, 1] as const;

/** 选项依次从左滑入，间隔 70ms。 */
const OPTION_LIST: Variants = {
  hidden: {},
  show: { transition: { staggerChildren: 0.07, delayChildren: 0.12 } },
};
const OPTION_ITEM: Variants = {
  hidden: { opacity: 0, x: -14 },
  show: { opacity: 1, x: 0, transition: { duration: 0.35, ease: EASE } },
};

/** 数字键直选只认 1–9。 */
const MAX_HOTKEYS = 9;

/** 焦点在可输入元素里时，数字键是在打字，不是在选。 */
function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return (
    target.isContentEditable ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.tagName === "SELECT"
  );
}

/**
 * 三种输入模式：options / free_input / options_with_fallback。
 *
 * 每个 interaction 是一张独立的卡：换了 `interaction_id` 旧卡先退场、新卡再进场，
 * 选项依次滑入。轮到学生时卡边有一段流光绕行，提交后流光转快，直到引擎推进完。
 */
export function InteractionCard() {
  const interaction = useGameStore((s) => s.interaction);
  // 自由输入的草稿放在外层：换卡时不丢（学生写了一半又改点选项，草稿还在）
  const [freeText, setFreeText] = useState("");

  return (
    <MotionRoot>
      <AnimatePresence mode="wait">
        {interaction && (
          <InteractionBody
            key={interaction.interaction_id}
            interaction={interaction}
            freeText={freeText}
            setFreeText={setFreeText}
          />
        )}
      </AnimatePresence>
    </MotionRoot>
  );
}

function InteractionBody({
  interaction,
  freeText,
  setFreeText,
}: {
  interaction: ActiveInteraction;
  freeText: string;
  setFreeText: (update: (prev: string) => string) => void;
}) {
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const pending = useGameStore((s) => s.pending);
  const connection = useGameStore((s) => s.connection);
  const submit = useGameStore((s) => s.submitCommand);
  const sessionId = useGameStore((s) => s.sessionId);
  const [chosenId, setChosenId] = useState<string | null>(null);

  const busy = pending !== null || connection !== "connected";
  const canChoose = allowedCommands.includes("choose_option");
  const canFree = allowedCommands.includes("free_input");
  const yourTurn = canChoose || canFree;
  const options = interaction.options;

  const extraCommands = allowedCommands.filter(
    (k): k is Extract<CommandKind, "enter_stage3" | "confirm_ending" | "exit_game"> =>
      k === "enter_stage3" || k === "confirm_ending" || k === "exit_game"
  );

  // 数字键直选：焦点不在输入框里、没按修饰键时，按 1–9 等于点对应选项
  useEffect(() => {
    if (!canChoose || busy) return;
    function onKeyDown(e: globalThis.KeyboardEvent) {
      if (e.defaultPrevented || e.isComposing) return;
      if (e.altKey || e.ctrlKey || e.metaKey) return;
      if (isTypingTarget(e.target)) return;
      const n = Number(e.key);
      if (!Number.isInteger(n) || n < 1 || n > Math.min(MAX_HOTKEYS, options.length)) {
        return;
      }
      e.preventDefault();
      const opt = options[n - 1];
      setChosenId(opt.option_id);
      submit("choose_option", { option_id: opt.option_id }, `选项 ${opt.label}`);
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [canChoose, busy, options, submit]);

  function choose(opt: OptionItem) {
    if (busy) return;
    setChosenId(opt.option_id);
    submit("choose_option", { option_id: opt.option_id }, `选项 ${opt.label}`);
  }

  function sendFreeInput() {
    const text = freeText.trim();
    if (!text || busy || !canFree) return;
    submit("free_input", { text }, "自由输入");
    setFreeText(() => "");
  }

  function onComposerKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey) return;
    // 输入法选词时的回车是「上屏」不是发送。Safari 在 keydown 时 isComposing 已复位，
    // 只能再看一眼 keyCode 229。
    if (e.nativeEvent.isComposing || e.keyCode === 229) return;
    e.preventDefault();
    sendFreeInput();
  }

  // 选中态只在等待引擎时成立；命令失败、pending 清空后选项全部恢复可点
  const activeChoice = pending ? chosenId : null;

  return (
    <m.div
      initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: 10, filter: "blur(4px)" }}
      transition={{ duration: 0.4, ease: EASE }}
      className={`glass relative rounded-3xl px-4 py-3.5 md:px-5 ${
        yourTurn || pending ? "glow-border" : ""
      }`}
      style={{ "--wj-glow-speed": pending ? "2.2s" : "7s" } as CSSProperties}
    >
      <div className="flex items-start gap-2.5">
        {yourTurn && (
          <span
            aria-hidden
            className="mt-2.5 size-1.5 shrink-0 rounded-full bg-flag shadow-[0_0_8px_var(--wj-flag)]"
          />
        )}
        <div className="min-w-0">
          <p className="font-serif text-lg text-ink">
            {interaction.prompt || "请选择你的行动"}
          </p>
          {interaction.hint && (
            <p className="mt-0.5 text-xs text-ink-faint">{interaction.hint}</p>
          )}
        </div>
      </div>

      {/* 抉择按整行排：选项往往是整句中文，左对齐的条目比一排药丸好读 */}
      {canChoose && options.length > 0 && (
        <m.ol
          variants={OPTION_LIST}
          initial="hidden"
          animate="show"
          className="mt-3 flex flex-col gap-2"
        >
          {options.map((opt, i) => {
            const chosen = activeChoice === opt.option_id;
            return (
              <m.li key={opt.option_id} variants={OPTION_ITEM}>
                <m.button
                  type="button"
                  disabled={busy}
                  data-chosen={chosen}
                  whileTap={{ scale: 0.985 }}
                  onClick={() => choose(opt)}
                  aria-keyshortcuts={i < MAX_HOTKEYS ? String(i + 1) : undefined}
                  className={[
                    "choice-glow group relative flex w-full items-center gap-3 overflow-hidden",
                    "rounded-2xl border border-glass-edge px-3.5 py-2.5 text-left font-serif text-base text-ink",
                    "transition-[opacity,background-color] duration-300 disabled:pointer-events-none",
                    chosen ? "bg-surface/80" : "bg-surface/35 hover:bg-surface/65",
                    busy && !chosen ? "opacity-40" : "opacity-100",
                  ].join(" ")}
                >
                  {i < MAX_HOTKEYS && (
                    <kbd
                      aria-hidden
                      className={`grid size-6 shrink-0 place-items-center rounded-md border font-sans text-xs transition-colors ${
                        chosen
                          ? "border-glow-jade/70 text-glow-jade"
                          : "border-glass-edge text-ink-faint group-hover:border-glow-jade/60 group-hover:text-glow-jade"
                      }`}
                    >
                      {i + 1}
                    </kbd>
                  )}
                  <span className="min-w-0 flex-1">{opt.label}</span>
                </m.button>
              </m.li>
            );
          })}
        </m.ol>
      )}

      {canFree && (
        <div className="mt-3">
          <div className="flex items-end gap-1.5 rounded-2xl border border-glass-edge bg-sunken/55 p-1.5 pl-3.5 transition-[border-color,box-shadow] duration-200 focus-within:border-glow-jade/50 focus-within:shadow-[0_0_0_3px_color-mix(in_srgb,var(--wj-glow-jade)_16%,transparent)]">
            <textarea
              value={freeText}
              onChange={(e) => setFreeText(() => e.target.value)}
              onKeyDown={onComposerKeyDown}
              placeholder={options.length > 0 ? "或写下你的行动…" : "写下你的行动…"}
              aria-label="写下你的行动"
              rows={2}
              maxLength={2000}
              disabled={busy}
              className="min-w-0 flex-1 resize-none bg-transparent py-1.5 font-serif text-base text-ink placeholder:text-ink-faint focus-visible:outline-none disabled:opacity-60"
            />
            {/* 语音是增强输入通道：识别结果填进输入框，键盘路径不受影响（#64） */}
            <VoiceInput
              sessionId={sessionId}
              disabled={busy}
              onText={(text) => setFreeText((prev) => (prev ? `${prev}${text}` : text))}
            />
            <Button
              tone="glow"
              size="sm"
              onClick={sendFreeInput}
              disabled={busy || !freeText.trim()}
            >
              <SendIcon />
              发送
            </Button>
          </div>
          <p className="mt-1.5 pl-1 text-2xs text-ink-faint">
            Enter 发送，Shift + Enter 换行
            {canChoose && options.length > 0 ? "；也可以直接按数字键选上面的选项" : ""}
          </p>
        </div>
      )}

      {!yourTurn && !pending && (
        <p className="mt-3 text-xs text-ink-faint">等待剧情推进…</p>
      )}

      {extraCommands.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-glass-edge pt-3">
          {extraCommands.map((k) =>
            k === "exit_game" ? (
              <button
                key={k}
                type="button"
                disabled={busy}
                onClick={() => submit(k, {}, EXTRA_LABELS[k])}
                className={buttonClass("quiet", "xs")}
              >
                {EXTRA_LABELS[k]}
              </button>
            ) : (
              <Button
                key={k}
                tone="glow"
                size="sm"
                disabled={busy}
                onClick={() => submit(k, {}, EXTRA_LABELS[k])}
              >
                {EXTRA_LABELS[k]}
              </Button>
            )
          )}
        </div>
      )}

      {pending && (
        <Thinking
          label={`正在推进 ${pending.label}`}
          since={pending.sentAt}
          announce={false}
          className="mt-3 text-xs"
        />
      )}
    </m.div>
  );
}

const EXTRA_LABELS: Record<string, string> = {
  enter_stage3: "进入剧情续写",
  confirm_ending: "确认结局",
  exit_game: "退出游戏",
};
