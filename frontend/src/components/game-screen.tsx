"use client";

import { useEffect, useState } from "react";

import { useAssetUrl } from "@/lib/asset-url";
import { useSpeakingSpeakers } from "@/lib/audio-session";
import { useCastRoster } from "@/lib/cast-roster";
import { sceneStatus, sceneStatusText } from "@/lib/session-status";
import { useMediaQuery } from "@/lib/use-media-query";
import { useGameStore } from "@/stores/gameStore";
import { useEffectsLevel, useUiStore } from "@/stores/uiStore";
import { ActCurtain } from "@/components/act-curtain";
import { EndingCard } from "@/components/ending-card";
import { GameHud } from "@/components/game-hud";
import { GameStage } from "@/components/game-stage";
import { InteractionCard } from "@/components/interaction-card";
import { sceneHasOriginal, sceneIdOf } from "@/components/original-text-panel";
import { StageFigures } from "@/components/stage-figures";
import { SubtitleTrack } from "@/components/subtitle-track";
import { TranscriptPanel, type TranscriptTab } from "@/components/transcript-panel";
import { BookIcon } from "@/components/ui/icons";
import { MotionRoot } from "@/components/ui/motion-root";

/**
 * 游玩页的整块舞台（视觉小说式版式）：
 *
 * ```
 * ┌ 顶栏 ─────────────────────────────────────────────┐
 * │ 头像组                                  ┌ 剧情回顾 ┐│
 * │      立绘层（台上最多三人，说话的人上前）  │ 剧情/角色 ││
 * │ ── 对白字幕带 ──────────────────────     │ 消息流   ││
 * │ ┌ 抉择卡 ─────────────────────────┐    │ 回溯栏   ││
 * └─────────────────────────────────────────────────────┘
 * ```
 *
 * 全部数据从 gameStore 读：游戏页负责接 WS 和拉状态，/showcase 往 store 里灌假数据，
 * 两边渲染的是同一份版式，不再各抄一份。
 */
export function GameScreen() {
  const sessionId = useGameStore((s) => s.sessionId);
  const stage = useGameStore((s) => s.stage);
  const scriptTitle = useGameStore((s) => s.scriptTitle);
  const messages = useGameStore((s) => s.messages);
  const streams = useGameStore((s) => s.streams);
  const playerRole = useGameStore((s) => s.playerRole);
  const connection = useGameStore((s) => s.connection);
  const sessionInitialized = useGameStore((s) => s.sessionInitialized);
  const pending = useGameStore((s) => s.pending);
  const sceneKey = useGameStore((s) => s.sceneKey);
  const sceneTitle = useGameStore((s) => s.sceneTitle);
  const currentAsset = useGameStore((s) => s.currentAsset);
  const scenes = useGameStore((s) => s.scenes);
  const hydrateEffects = useUiStore((s) => s.hydrateEffects);
  const effects = useEffectsLevel();
  const speaking = useSpeakingSpeakers();
  // WS 连上不等于能玩：Stage3 的 session_init 会先补算离线 tick（最多 3 轮 LLM）。
  const status = sceneStatus(connection, sessionInitialized);

  // 背景稳定引用 → 预签名 URL（#53）：按 current_asset 变化现取（短时效），
  // 取不到就交给 GameStage 降级为无图渐变，不阻塞游玩。
  const { url: backgroundUrl } = useAssetUrl(currentAsset);

  useEffect(() => {
    hydrateEffects();
  }, [hydrateEffects]);

  // 剧情回顾：宽屏默认展开、窄屏默认收起；学生点过开关后就听学生的
  const wide = useMediaQuery("(min-width: 1024px)");
  const [userOpen, setUserOpen] = useState<boolean | null>(null);
  const transcriptOpen = userOpen ?? wide;
  const [tab, setTab] = useState<TranscriptTab>("story");

  const { cast, listed } = useCastRoster();
  const currentScene = scenes.find((sc) => sc.scene_id === sceneIdOf(sceneKey));
  function openTranscript(next: TranscriptTab) {
    setTab(next);
    setUserOpen(true);
  }

  return (
    <MotionRoot>
      <div data-effects={effects} className="relative flex min-h-0 flex-1 flex-col">
        <GameStage
          backgroundUrl={backgroundUrl}
          sceneKey={sceneKey}
          sceneTitle={sceneTitle}
        >
          <GameHud
            sessionId={sessionId ?? ""}
            stage={stage}
            scriptTitle={scriptTitle}
            playerRole={playerRole}
            connection={connection}
            pending={pending}
            transcriptOpen={transcriptOpen}
            onToggleTranscript={() => setUserOpen(!transcriptOpen)}
          />

          <div className="relative flex min-h-0 flex-1 gap-3 p-3 md:gap-4 md:p-4">
            <section className="flex min-h-0 min-w-0 flex-1 flex-col gap-3">
              <div className="relative min-h-0 flex-1">
                <StageFigures
                  cast={cast}
                  characters={listed}
                  playerRole={playerRole}
                  speaking={speaking}
                />
                {sceneHasOriginal(currentScene) && (
                  <button
                    type="button"
                    onClick={() => openTranscript("text")}
                    className="absolute top-3 right-3 z-20 flex items-center gap-1.5 rounded-full border border-glass-edge bg-glass px-3 py-1.5 text-xs text-ink-soft backdrop-blur-md transition-[color,box-shadow] hover:text-glow-gold hover:shadow-[0_0_16px_-4px_var(--wj-glow-gold)]"
                  >
                    <BookIcon />
                    对照原文
                  </button>
                )}
                {messages.length === 0 && streams.length === 0 && (
                  <div
                    role="status"
                    aria-live="polite"
                    className="absolute inset-0 grid place-items-center"
                  >
                    <p className="flex flex-col items-center gap-1 text-sm text-ink-faint">
                      <span>{sceneStatusText(status)}</span>
                      {status === "restoring" && (
                        <span className="text-2xs">
                          离线期间世界仍在演进，正在补算。
                        </span>
                      )}
                    </p>
                  </div>
                )}
                <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10">
                  <SubtitleTrack
                    messages={messages}
                    streams={streams}
                    playerRole={playerRole}
                  />
                </div>
              </div>
              <InteractionCard />
            </section>

            <TranscriptPanel
              open={transcriptOpen}
              overlay={!wide}
              tab={tab}
              onTabChange={setTab}
              onClose={() => setUserOpen(false)}
            />
          </div>
        </GameStage>

        <ActCurtain />
        <EndingCard onReview={() => openTranscript("story")} />
      </div>
    </MotionRoot>
  );
}
