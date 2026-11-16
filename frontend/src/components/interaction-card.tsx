"use client";

import {
  useCallback,
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
  StageValue,
} from "@/lib/contracts/types";
import { useGameStore } from "@/stores/gameStore";
import { isImeEnter } from "@/lib/ime";
import { useInteractionBusy } from "@/lib/interaction-busy";
import { Thinking } from "@/components/thinking";
import { VoiceInput } from "@/components/voice-input";
import { Button, buttonClass, iconButtonClass } from "@/components/ui/button";
import { CloseIcon, DialogueIcon, SendIcon } from "@/components/ui/icons";
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

/** 面板容器的锚点：圆钮的 `aria-controls` 指向它。 */
const DOCK_ID = "action-dock";

/** 轮到你出牌：有选项或能自由输入（展开态的流光、收起态的朱砂点同一口径）。 */
function isYourTurn(allowed: readonly CommandKind[]): boolean {
  return allowed.includes("choose_option") || allowed.includes("free_input");
}

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
 * 整块行动面板（场景信息、选项、自由输入）按轮自动收放：**提交后收起、下一轮交互点
 * 就绪时弹出**，平时只在舞台左下角留一颗圆钮——底下一大块玻璃框会把背景与立绘压掉
 * 半屏，而它多数时候只是「看得出牌时才需要」。收起态在圆钮上点一颗朱砂，免得面板收着、
 * 学生错过出牌。展开后每个 interaction 仍是一张独立的卡：换了 `interaction_id` 旧卡先
 * 退场、新卡再进场，选项依次滑入。
 * 轮到学生时卡边有一段流光绕行，提交后流光转快，直到引擎推进完。
 *
 * 换景与干涉入口在侧栏（`TranscriptPanel`），这里只留本轮选项与自由输入，
 * 舞台下半屏不再被两排工具占满。窄屏侧栏收起时，卡上补一对直达入口
 * （`showOperations`），否则玩家找不到换景/干涉。
 */
export function InteractionCard({
  showOperations = false,
  onRequestOperations,
}: {
  /** 侧栏收起时在卡上显示「场景移动 / 干涉世界」直达按钮 */
  showOperations?: boolean;
  onRequestOperations?: (panel: "move" | "intervene") => void;
}) {
  const interaction = useGameStore((s) => s.interaction);
  const stage = useGameStore((s) => s.stage);
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const pending = useGameStore((s) => s.pending);
  // 自由输入的草稿放在最外层：换卡、收起面板都不丢（学生写了一半又去点选项）
  const [freeText, setFreeText] = useState("");
  // 收起的是「哪一张卡」，不是一个布尔：记下被玩家收起的键（交互点 id，或阶段卡的
  // `phase:{stage}`）。新的一轮交互点一到键就变了，面板自己弹出来——出牌时它在，
  // 提交后它退场，玩家只在想单看舞台时手动收一次。
  const [collapsedKey, setCollapsedKey] = useState<string | null>(null);
  const extras = visibleExtras(allowedCommands, stage);
  const dockKey = interaction ? interaction.interaction_id : `phase:${stage}`;
  // 提交后收起：回调身份跟着 dockKey 走，交互点没换就不重挂数字键监听
  const collapseDock = useCallback(
    () => setCollapsedKey(dockKey),
    [dockKey]
  );

  // 没得选也没阶段命令时整颗圆钮都不渲染，免得贴着一颗点了没反应的按钮
  if (!interaction && extras.length === 0) return null;

  const open = collapsedKey !== dockKey;

  // 轮到你出牌（或停在阶段之间等你决定）→ 收起态在圆钮上点一颗朱砂
  const waiting = interaction ? isYourTurn(allowedCommands) : extras.length > 0;
  const showTurnDot = !open && !pending && waiting;

  return (
    <MotionRoot>
      <div className="flex w-full items-end gap-2">
        <button
          type="button"
          onClick={() => setCollapsedKey(open ? dockKey : null)}
          aria-expanded={open}
          aria-controls={open ? DOCK_ID : undefined}
          aria-label={
            open
              ? "收起行动面板"
              : waiting
                ? "展开行动面板（轮到你行动）"
                : "展开行动面板"
          }
          title={open ? "收起行动面板" : "展开行动面板"}
          className={iconButtonClass(false, "relative", "lg")}
        >
          {open ? <CloseIcon /> : <DialogueIcon />}
          {showTurnDot && (
            <span
              aria-hidden
              className="absolute top-0 right-0 size-2.5 rounded-full bg-flag shadow-[0_0_10px_var(--wj-flag)]"
            />
          )}
        </button>
        <AnimatePresence mode="wait">
          {open ? (
            interaction ? (
              <InteractionBody
                key={interaction.interaction_id}
                interaction={interaction}
                extras={extras}
                freeText={freeText}
                setFreeText={setFreeText}
                showOperations={showOperations}
                onRequestOperations={onRequestOperations}
                onSubmitted={collapseDock}
              />
            ) : (
              <PhaseCard key={`phase:${stage}`} stage={stage} commands={extras} />
            )
          ) : null}
        </AnimatePresence>
      </div>
    </MotionRoot>
  );
}

type ExtraCommand = Extract<CommandKind, "enter_stage3" | "confirm_ending" | "exit_game">;

function isExtraCommand(k: CommandKind): k is ExtraCommand {
  return k === "enter_stage3" || k === "confirm_ending" || k === "exit_game";
}

/**
 * 当前阶段实际渲染的阶段命令。
 *
 * `confirm_ending` 是旧契约里给「课文结局确认」用的收束命令，仍冻结在
 * `ALLOWED_COMMANDS` 里；但 Stage3 自由探索没有叙事结局，在续写阶段展示它
 * 只会把玩家带进一个没有结局卡的死角。关闭本局走 `exit_game`。
 */
function visibleExtras(
  allowed: readonly CommandKind[],
  stage: StageValue
): ExtraCommand[] {
  return allowed
    .filter(isExtraCommand)
    .filter((k) => !(stage === "stage3_extending" && k === "confirm_ending"));
}

/** 阶段卡的引导语：没有交互点、只剩阶段命令时（如还原演完）告诉学生下一步是什么。 */
const PHASE_PROMPTS: Partial<Record<StageValue, { prompt: string; hint: string }>> = {
  stage2_complete: {
    prompt: "课文演完了。",
    hint: "可以接着续写，看看故事还能怎么走；也可以到此为止。",
  },
};

/** 阶段命令按钮：进入续写、确认结局用主按钮，退出游戏用文字链。 */
function ExtraCommands({ commands, busy }: { commands: ExtraCommand[]; busy: boolean }) {
  const submit = useGameStore((s) => s.submitCommand);
  return (
    <>
      {commands.map((k) =>
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
    </>
  );
}

/**
 * 阶段卡：引擎停在阶段之间（还原演完、等学生决定是否续写）时没有交互点，
 * 只有 `enter_stage3` / `exit_game` 这类阶段命令。此前这里整张卡不渲染，
 * 学生找不到进入续写的入口。
 */
function PhaseCard({ stage, commands }: { stage: StageValue; commands: ExtraCommand[] }) {
  const pending = useGameStore((s) => s.pending);
  const sessionInitialized = useGameStore((s) => s.sessionInitialized);
  const busy = useInteractionBusy();
  const copy = PHASE_PROMPTS[stage];

  return (
    <m.div
      id={DOCK_ID}
      initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: 10, filter: "blur(4px)" }}
      transition={{ duration: 0.4, ease: EASE }}
      className="glass glow-border relative min-w-0 flex-1 rounded-3xl px-4 py-3.5 md:px-5"
      style={{ "--wj-glow-speed": pending ? "2.2s" : "7s" } as CSSProperties}
    >
      {copy && (
        <>
          <p className="font-serif text-lg text-ink">{copy.prompt}</p>
          <p className="mt-0.5 text-xs text-ink-faint">{copy.hint}</p>
        </>
      )}
      <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 ${copy ? "mt-3" : ""}`}>
        <ExtraCommands commands={commands} busy={busy} />
      </div>
      {pending && (
        <Thinking
          label={`正在推进 ${pending.label}`}
          since={pending.sentAt}
          announce={false}
          className="mt-3 text-xs"
        />
      )}
      {!sessionInitialized && !pending && (
        <p className="mt-3 text-xs text-ink-faint">正在重建世界…</p>
      )}
    </m.div>
  );
}

function InteractionBody({
  interaction,
  extras: extraCommands,
  freeText,
  setFreeText,
  showOperations,
  onRequestOperations,
  onSubmitted,
}: {
  interaction: ActiveInteraction;
  /** 阶段命令（进入续写/退出游戏）：外层与本卡同一口径算一次，避免两处漂移 */
  extras: ExtraCommand[];
  freeText: string;
  setFreeText: (update: (prev: string) => string) => void;
  showOperations: boolean;
  onRequestOperations?: (panel: "move" | "intervene") => void;
  /** 本轮动作已提交：外层据此收起面板，等下一轮交互点再自动弹出 */
  onSubmitted: () => void;
}) {
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const pending = useGameStore((s) => s.pending);
  const sessionInitialized = useGameStore((s) => s.sessionInitialized);
  const submit = useGameStore((s) => s.submitCommand);
  const sessionId = useGameStore((s) => s.sessionId);
  const [chosenId, setChosenId] = useState<string | null>(null);
  // 选项默认收起：抉择卡是舞台下半屏最大的一块，展开四条整句中文就把背景压没了。
  // 每轮新卡（外层按 interaction_id 设 key）都会回到收起态。
  const [optionsOpen, setOptionsOpen] = useState(false);

  const busy = useInteractionBusy();
  const canChoose = allowedCommands.includes("choose_option");
  const canFree = allowedCommands.includes("free_input");
  const sceneOptions = interaction.scene_options ?? [];
  const currentScene = sceneOptions.find((scene) => scene.is_current);
  const yourTurn = isYourTurn(allowedCommands);
  const options = interaction.options;
  const quickMove = sceneOptions.length > 0 && allowedCommands.includes("switch_scene");
  const quickIntervene =
    sceneOptions.length > 0 && allowedCommands.includes("intervene");

  // 数字键直选：选项展开后、焦点不在输入框里、没按修饰键时，按 1–9 等于点对应选项。
  // 收起状态下不绑定：看不见选项时按键直接提交等于让玩家盲选。
  useEffect(() => {
    if (!canChoose || busy || !optionsOpen) return;
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
      onSubmitted();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [canChoose, busy, options, optionsOpen, onSubmitted, submit]);

  function choose(opt: OptionItem) {
    if (busy) return;
    setChosenId(opt.option_id);
    submit("choose_option", { option_id: opt.option_id }, `选项 ${opt.label}`);
    onSubmitted();
  }

  function sendText(
    kind: "free_input" | "intervene",
    text: string,
    allowed: boolean,
    reset: () => void,
    label: string,
  ) {
    const trimmed = text.trim();
    if (!trimmed || busy || !allowed) return;
    submit(kind, { text: trimmed }, label);
    reset();
    onSubmitted();
  }

  function sendFreeInput() {
    sendText("free_input", freeText, canFree, () => setFreeText(() => ""), "自由输入");
  }

  function onComposerKeyDown(e: KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key !== "Enter" || e.shiftKey) return;
    if (isImeEnter(e)) return;
    e.preventDefault();
    sendFreeInput();
  }

  // 选中态只在等待引擎时成立；命令失败、pending 清空后选项全部恢复可点
  const activeChoice = pending ? chosenId : null;

  return (
    <m.div
      id={DOCK_ID}
      initial={{ opacity: 0, y: 16, filter: "blur(6px)" }}
      animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
      exit={{ opacity: 0, y: 10, filter: "blur(4px)" }}
      transition={{ duration: 0.4, ease: EASE }}
      // 高度封顶 + 内部滚动：横屏/矮屏上选项与输入框不会被舞台裁掉；
      // 滚动放在内层，外层留作 glow-border 的定位容器（会随滚动一起走的伪元素不能裁）
      className={`glass relative flex max-h-[min(58dvh,34rem)] min-w-0 flex-1 flex-col rounded-3xl ${
        yourTurn || pending ? "glow-border" : ""
      }`}
      style={{ "--wj-glow-speed": pending ? "2.2s" : "7s" } as CSSProperties}
    >
      <div className="min-h-0 overflow-y-auto overscroll-contain px-4 py-3.5 md:px-5">
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
          {sceneOptions.length > 0 && (
            <p className="mt-1 text-xs text-ink-faint" aria-live="polite">
              当前在场：
              {currentScene && currentScene.participants.length > 0
                ? currentScene.participants.join("、")
                : "只有你"}
            </p>
          )}
        </div>
      </div>

      {/* 侧栏收起时的直达入口：换景与干涉藏在侧栏里，窄屏上不点开就找不到 */}
      {showOperations &&
        onRequestOperations &&
        (quickMove || quickIntervene) && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5 pl-4">
            {quickMove && (
              <button
                type="button"
                onClick={() => onRequestOperations("move")}
                className="rounded-full border border-glass-edge px-3 py-1 font-serif text-xs text-ink-soft transition-colors hover:border-glow-jade/60 hover:text-glow-jade"
              >
                场景移动
              </button>
            )}
            {quickIntervene && (
              <button
                type="button"
                onClick={() => onRequestOperations("intervene")}
                className="rounded-full border border-glass-edge px-3 py-1 font-serif text-xs text-ink-soft transition-colors hover:border-glow-gold/60 hover:text-glow-gold"
              >
                干涉世界
              </button>
            )}
          </div>
        )}

      {/* 选项默认收起：卡上只留一行入口，展开后才铺开整句中文的选项 */}
      {canChoose && options.length > 0 && (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setOptionsOpen((open) => !open)}
            aria-expanded={optionsOpen}
            aria-controls="interaction-options"
            className="flex w-full items-center justify-between rounded-2xl border border-glass-edge bg-surface/35 px-3.5 py-2 font-serif text-sm text-ink-soft transition-colors hover:bg-surface/60 hover:text-ink"
          >
            <span>
              {optionsOpen
                ? "收起行动选项"
                : `选择行动（${options.length} 个可选）`}
            </span>
            <span
              aria-hidden
              className={`text-xs transition-transform duration-200 ${
                optionsOpen ? "rotate-180" : ""
              }`}
            >
              ▾
            </span>
          </button>
          {optionsOpen && (
            <m.ol
              id="interaction-options"
              variants={OPTION_LIST}
              initial="hidden"
              animate="show"
              className="mt-2 flex flex-col gap-2"
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
                  {/* 还原阶段的选项是各角色的提议：标出是谁的主意，学生会去想他为什么这么做 */}
                  {opt.proposed_by && (
                    <span className="shrink-0 self-start rounded-full border border-glow-gold/30 px-2 py-0.5 font-sans text-2xs text-glow-gold">
                      {opt.proposed_by}的主意
                    </span>
                  )}
                </m.button>
              </m.li>
            );
          })}
        </m.ol>
          )}
        </div>
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
            {canChoose && options.length > 0 ? "；展开选项后可按数字键直选" : ""}
          </p>
        </div>
      )}

      {!yourTurn && !pending && (
        <p className="mt-3 text-xs text-ink-faint">等待剧情推进…</p>
      )}

      {extraCommands.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 border-t border-glass-edge pt-3">
          <ExtraCommands commands={extraCommands} busy={busy} />
        </div>
      )}

      {!sessionInitialized && !pending && (
        <p className="mt-3 text-xs text-ink-faint">正在重建世界…</p>
      )}

      {pending && (
        <Thinking
          label={`正在推进 ${pending.label}`}
          since={pending.sentAt}
          announce={false}
          className="mt-3 text-xs"
        />
      )}
      </div>
    </m.div>
  );
}

const EXTRA_LABELS: Record<string, string> = {
  enter_stage3: "进入剧情续写",
  confirm_ending: "确认结局",
  exit_game: "退出游戏",
};
