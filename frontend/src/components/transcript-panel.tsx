"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, m } from "motion/react";

import { latestInterventionFeedback } from "@/lib/intervention";
import { useInteractionBusy } from "@/lib/interaction-busy";
import { isImeEnter } from "@/lib/ime";
import { useGameStore } from "@/stores/gameStore";
import { sceneStatus, sceneStatusText } from "@/lib/session-status";
import { CastDock } from "@/components/cast-dock";
import { MessageStream } from "@/components/message-stream";
import { OriginalTextPanel } from "@/components/original-text-panel";
import { RolePanel } from "@/components/role-panel";
import { RollbackBar } from "@/components/rollback-bar";
import { Button } from "@/components/ui/button";
import { CloseIcon } from "@/components/ui/icons";
import { Tag } from "@/components/ui/tag";

export type TranscriptTab = "story" | "text" | "cast";

const TABS: { id: TranscriptTab; label: string }[] = [
  { id: "story", label: "剧情" },
  { id: "text", label: "原文" },
  { id: "cast", label: "角色" },
];

const EASE = [0.2, 0.7, 0.2, 1] as const;

/**
 * 剧情回顾面板：「剧情」页是完整消息流 + 回溯栏，「原文」页对照课文里已经演到的段落，
 * 「角色」页是人物档案。
 *
 * 宽屏（≥1024px）贴在舞台右侧常开；窄屏改成从右侧滑出的抽屉，点遮罩或按 Esc 收起。
 * 回溯目标在这里持有：消息流里每句旁的「回溯到这一句」直接跳到确认这一步，
 * 和回溯栏的下拉框指向同一个目标。
 */
export function TranscriptPanel({
  open,
  overlay,
  tab,
  onTabChange,
  onClose,
}: {
  open: boolean;
  /** 窄屏抽屉模式：浮在舞台上、带遮罩 */
  overlay: boolean;
  tab: TranscriptTab;
  onTabChange: (tab: TranscriptTab) => void;
  onClose: () => void;
}) {
  const messages = useGameStore((s) => s.messages);
  const playerRole = useGameStore((s) => s.playerRole);
  const characters = useGameStore((s) => s.characters);
  const playableRoles = useGameStore((s) => s.playableRoles);
  const allowedCommands = useGameStore((s) => s.allowedCommands);
  const sessionInitialized = useGameStore((s) => s.sessionInitialized);
  const connection = useGameStore((s) => s.connection);
  const scenes = useGameStore((s) => s.scenes);
  const sceneKey = useGameStore((s) => s.sceneKey);
  const stage = useGameStore((s) => s.stage);
  const interaction = useGameStore((s) => s.interaction);
  const submit = useGameStore((s) => s.submitCommand);
  const [target, setTarget] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  // 侧栏操作面板：场景移动 / 干涉世界。主舞台只留选项与输入。
  const [panel, setPanel] = useState<"move" | "intervene" | null>(null);
  const [interveneText, setInterveneText] = useState("");
  const canRollback = allowedCommands.includes("rollback_to_event");
  const status = sceneStatus(connection, sessionInitialized);
  const sceneOptions = interaction?.scene_options ?? [];
  const canMove = allowedCommands.includes("switch_scene") && sceneOptions.length > 0;
  const canIntervene =
    allowedCommands.includes("intervene") && sceneOptions.length > 0;
  const busy = useInteractionBusy();
  const interventionFeedback = latestInterventionFeedback(messages);

  function sendIntervene() {
    const text = interveneText.trim();
    if (!text || busy || !canIntervene) return;
    submit("intervene", { text }, "干涉世界");
    setInterveneText("");
    // 面板保持展开：提交后的「已生效 / 未应允」反馈就渲染在输入框下面
  }

  useEffect(() => {
    if (!open || !overlay) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, overlay, onClose]);

  return (
    <AnimatePresence>
      {open && overlay && (
        <m.div
          key="scrim"
          aria-hidden
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={onClose}
          className="absolute inset-0 z-30 bg-black/55"
        />
      )}
      {open && (
        <m.aside
          key="transcript"
          aria-label="剧情回顾"
          initial={{ opacity: 0, x: 28 }}
          animate={{ opacity: 1, x: 0 }}
          exit={{ opacity: 0, x: 28 }}
          transition={{ duration: 0.35, ease: EASE }}
          className={
            overlay
              ? "glass absolute inset-y-3 right-3 z-40 flex w-[min(24rem,calc(100%-1.5rem))] flex-col overflow-hidden rounded-3xl"
              : "glass relative flex w-[22rem] shrink-0 flex-col overflow-hidden rounded-3xl xl:w-[24rem]"
          }
        >
          <div className="flex items-center gap-1 border-b border-glass-edge px-3 pt-2.5">
            <div role="tablist" aria-label="剧情回顾" className="flex flex-1 gap-1">
              {TABS.map((t) => {
                const selected = tab === t.id;
                return (
                  <button
                    key={t.id}
                    type="button"
                    role="tab"
                    id={`transcript-tab-${t.id}`}
                    aria-selected={selected}
                    aria-controls={`transcript-panel-${t.id}`}
                    onClick={() => onTabChange(t.id)}
                    className={`relative px-3 pb-2.5 font-serif text-sm transition-colors ${
                      selected ? "text-ink" : "text-ink-faint hover:text-ink-soft"
                    }`}
                  >
                    {t.label}
                    {selected && (
                      <m.span
                        layoutId="transcript-tab-underline"
                        className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-linear-to-r from-glow-gold to-glow-jade"
                      />
                    )}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              onClick={onClose}
              aria-label="收起剧情回顾"
              title="收起"
              className="mb-2 grid size-7 place-items-center rounded-full text-base text-ink-faint transition-colors hover:text-ink"
            >
              <CloseIcon />
            </button>
          </div>

          {(canMove || canIntervene) && (
            <div className="flex flex-wrap items-center gap-1.5 border-b border-glass-edge px-3 py-2">
              <span className="mr-1 font-sans text-2xs uppercase tracking-[0.2em] text-ink-faint">
                操作
              </span>
              {canMove && (
                <button
                  type="button"
                  aria-pressed={panel === "move"}
                  onClick={() =>
                    setPanel((current) => (current === "move" ? null : "move"))
                  }
                  className={`rounded-full border px-3 py-1 font-serif text-sm transition-colors ${
                    panel === "move"
                      ? "border-glow-jade/60 text-glow-jade"
                      : "border-glass-edge text-ink-soft hover:text-ink"
                  }`}
                >
                  场景移动
                </button>
              )}
              {canIntervene && (
                <button
                  type="button"
                  aria-pressed={panel === "intervene"}
                  onClick={() =>
                    setPanel((current) =>
                      current === "intervene" ? null : "intervene"
                    )
                  }
                  className={`rounded-full border px-3 py-1 font-serif text-sm transition-colors ${
                    panel === "intervene"
                      ? "border-glow-gold/60 text-glow-gold"
                      : "border-glass-edge text-ink-soft hover:text-ink"
                  }`}
                >
                  干涉世界
                </button>
              )}
            </div>
          )}

          {panel === "move" && (
            <div className="border-b border-glass-edge px-3 py-2">
              <div role="group" aria-label="换景" className="flex flex-wrap gap-1.5">
                {sceneOptions.map((scene) => (
                  <button
                    key={scene.scene_key}
                    type="button"
                    disabled={busy || scene.is_current}
                    aria-current={scene.is_current || undefined}
                    onClick={() => {
                      submit(
                        "switch_scene",
                        { scene_key: scene.scene_key },
                        `前往 ${scene.title}`
                      );
                      setPanel(null);
                    }}
                    className={[
                      "rounded-full border px-3 py-1 font-serif text-sm transition-colors",
                      scene.is_current
                        ? "border-glass-edge/60 text-ink-faint"
                        : "border-glass-edge text-ink hover:border-glow-jade/60 hover:text-glow-jade",
                      busy && !scene.is_current ? "opacity-40" : "opacity-100",
                    ].join(" ")}
                  >
                    {scene.title}
                    {scene.is_current && <span className="ml-1">（当前）</span>}
                  </button>
                ))}
              </div>
            </div>
          )}

          {panel === "intervene" && (
            <div className="border-b border-glass-edge px-3 py-2">
              <div className="flex items-center gap-1.5 rounded-2xl border border-dashed border-glass-edge bg-surface/20 p-1 pl-3 transition-[border-color] duration-200 focus-within:border-glow-gold/50">
                <input
                  value={interveneText}
                  onChange={(e) => setInterveneText(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key !== "Enter" || isImeEnter(e)) return;
                    e.preventDefault();
                    sendIntervene();
                  }}
                  placeholder="如：建一间雨夜客栈 / 叫船夫过来"
                  aria-label="干涉世界"
                  maxLength={2000}
                  disabled={busy}
                  className="min-w-0 flex-1 bg-transparent py-1.5 font-serif text-sm text-ink placeholder:text-ink-faint focus-visible:outline-none disabled:opacity-60"
                />
                <Button
                  tone="glow"
                  size="sm"
                  onClick={sendIntervene}
                  disabled={busy || !interveneText.trim()}
                >
                  干涉
                </Button>
              </div>
              <p className="mt-1.5 pl-1 text-2xs text-ink-faint">
                每轮可以干涉一次；世界构建可能不答应。
              </p>
              {interventionFeedback && (
                <p
                  role="status"
                  className="mt-1 flex flex-wrap items-baseline gap-1.5 pl-1 text-xs"
                >
                  <Tag
                    tone={
                      interventionFeedback.status === "applied" ? "ok" : "warn"
                    }
                  >
                    {interventionFeedback.status === "applied" ? "已生效" : "未应允"}
                  </Tag>
                  <span className="min-w-0 flex-1 text-ink-soft">
                    {interventionFeedback.text}
                  </span>
                </p>
              )}
            </div>
          )}

          <div className="border-b border-glass-edge px-3 py-2">
            <p className="mb-1.5 font-sans text-2xs uppercase tracking-[0.2em] text-ink-faint">
              在场
            </p>
            <CastDock />
          </div>

          {tab === "story" ? (
            <div
              role="tabpanel"
              id="transcript-panel-story"
              aria-labelledby="transcript-tab-story"
              className="flex min-h-0 flex-1 flex-col"
            >
              {/* 左边多留一截给开发环境的事件序号 */}
              <div className="min-h-0 flex-1 overflow-y-auto py-2 pr-3 pl-8">
                {messages.length === 0 ? (
                  <p className="py-6 text-center text-sm text-ink-faint">
                    {sceneStatusText(status)}
                  </p>
                ) : (
                  <MessageStream
                    messages={messages}
                    playerRole={playerRole}
                    showSeq={process.env.NODE_ENV !== "production"}
                    rollbackTarget={target}
                    onRollback={
                      canRollback
                        ? (seq) => {
                            setTarget(seq);
                            setConfirming(true);
                          }
                        : undefined
                    }
                  />
                )}
              </div>
              <RollbackBar
                target={target}
                confirming={confirming}
                onTargetChange={setTarget}
                onConfirmingChange={setConfirming}
              />
            </div>
          ) : tab === "text" ? (
            <div
              role="tabpanel"
              id="transcript-panel-text"
              aria-labelledby="transcript-tab-text"
              className="min-h-0 flex-1 overflow-y-auto p-3"
            >
              <OriginalTextPanel scenes={scenes} sceneKey={sceneKey} stage={stage} />
            </div>
          ) : (
            <div
              role="tabpanel"
              id="transcript-panel-cast"
              aria-labelledby="transcript-tab-cast"
              className="min-h-0 flex-1 overflow-y-auto p-3"
            >
              <RolePanel
                characters={characters}
                messages={messages}
                playableRoles={playableRoles}
                playerRole={playerRole}
              />
            </div>
          )}
        </m.aside>
      )}
    </AnimatePresence>
  );
}
