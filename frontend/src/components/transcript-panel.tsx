"use client";

import { useEffect, useState } from "react";
import { AnimatePresence, m } from "motion/react";

import { useGameStore } from "@/stores/gameStore";
import { MessageStream } from "@/components/message-stream";
import { OriginalTextPanel } from "@/components/original-text-panel";
import { RolePanel } from "@/components/role-panel";
import { RollbackBar } from "@/components/rollback-bar";
import { CloseIcon } from "@/components/ui/icons";

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
  const scenes = useGameStore((s) => s.scenes);
  const sceneKey = useGameStore((s) => s.sceneKey);
  const stage = useGameStore((s) => s.stage);
  const [target, setTarget] = useState<number | null>(null);
  const [confirming, setConfirming] = useState(false);
  const canRollback = allowedCommands.includes("rollback_to_event");

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
                  <p className="py-6 text-center text-sm text-ink-faint">等待剧情开始…</p>
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
