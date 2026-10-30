"use client";

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useAssetUrl } from "@/lib/asset-url";
import { useGameChannel } from "@/lib/ws";
import { getStatus } from "@/lib/api";
import { stageLabel } from "@/lib/labels";
import { loadRecents, upsertRecent } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import { AudioControls } from "@/components/audio-controls";
import { GameStage } from "@/components/game-stage";
import { InteractionCard } from "@/components/interaction-card";
import { MessageStream } from "@/components/message-stream";
import { RolePanel } from "@/components/role-panel";
import { RollbackBar } from "@/components/rollback-bar";
import { SubtitleTrack } from "@/components/subtitle-track";
import { ToastHost } from "@/components/toast-host";
import { buttonClass } from "@/components/ui/button";
import { Loading } from "@/components/ui/states";
import { Tag } from "@/components/ui/tag";

/** 连接状态：一枚色点 + 短语，比单靠文字颜色更易在背景图上辨认。 */
const CONNECTION_LABELS: Record<string, { text: string; dot: string }> = {
  idle: { text: "未连接", dot: "bg-ink-faint" },
  connecting: { text: "连接中…", dot: "bg-warn" },
  connected: { text: "已连接", dot: "bg-ok" },
  reconnecting: { text: "重连中…", dot: "bg-warn animate-pulse" },
  closed: { text: "已断开", dot: "bg-danger" },
};

function GameContent() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("id");

  const stage = useGameStore((s) => s.stage);
  const messages = useGameStore((s) => s.messages);
  const streams = useGameStore((s) => s.streams);
  const characters = useGameStore((s) => s.characters);
  const playableRoles = useGameStore((s) => s.playableRoles);
  const playerRole = useGameStore((s) => s.playerRole);
  const connection = useGameStore((s) => s.connection);
  const pending = useGameStore((s) => s.pending);
  const sceneKey = useGameStore((s) => s.sceneKey);
  const sceneTitle = useGameStore((s) => s.sceneTitle);
  const currentAsset = useGameStore((s) => s.currentAsset);
  const resetSession = useGameStore((s) => s.resetSession);
  const setStatusInfo = useGameStore((s) => s.setStatusInfo);

  const push = useUiStore((s) => s.push);

  // 背景稳定引用 → 预签名 URL（#53）：按 current_asset 变化现取（短时效），
  // 取不到就交给 GameStage 降级为无图渐变，不阻塞游玩。
  const { url: backgroundUrl } = useAssetUrl(currentAsset);

  useGameChannel(sessionId);

  useEffect(() => {
    if (!sessionId) return;
    if (useGameStore.getState().sessionId !== sessionId) {
      resetSession(sessionId);
    }
  }, [sessionId, resetSession]);

  // 刷新恢复：REST 状态查询补齐头部信息（角色/阶段），并记录最近会话
  // scriptId：优先取 URL（开局/选角链路携带），否则保留 localStorage 里的旧值，
  // 避免每次游戏页刷新都把记录的剧本来源覆盖丢失。
  useEffect(() => {
    if (!sessionId) return;
    let cancelled = false;
    getStatus(sessionId)
      .then((status) => {
        if (cancelled) return;
        setStatusInfo(status);
        const scriptParam = searchParams.get("script");
        const scriptId = scriptParam
          ? Number(scriptParam)
          : (loadRecents().find((r) => r.sessionId === sessionId)?.scriptId ??
            null);
        upsertRecent({
          sessionId,
          stage: status.stage,
          title: useGameStore.getState().scriptTitle,
          playerRole: status.selected_role,
          scriptId,
          updatedAt: new Date().toISOString(),
        });
      })
      .catch(() => {
        if (!cancelled) {
          push({ kind: "error", title: "会话状态查询失败", description: "可能不存在该会话" });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [sessionId, searchParams, setStatusInfo, push]);

  if (!sessionId) {
    return (
      <main
        data-surface="stage"
        className="flex flex-1 flex-col items-center justify-center gap-4 bg-canvas p-8"
      >
        <p className="font-serif text-lg">缺少会话参数。</p>
        <Link href="/" className={buttonClass("outline", "sm")}>
          返回首页
        </Link>
        <ToastHost />
      </main>
    );
  }

  const conn = CONNECTION_LABELS[connection] ?? CONNECTION_LABELS.idle;

  return (
    <main
      data-surface="stage"
      className="flex h-screen w-full flex-col overflow-hidden bg-canvas"
    >
      <GameStage
        backgroundUrl={backgroundUrl}
        sceneKey={sceneKey}
        sceneTitle={sceneTitle}
      >
        <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-rule bg-panel px-4 py-2.5 backdrop-blur-md">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <span className="font-serif text-lg font-semibold tracking-[0.18em]">
              文境
            </span>
            <span className="font-mono text-2xs text-ink-faint">
              {sessionId.slice(0, 8)}
            </span>
            <Tag>{stageLabel(stage)}</Tag>
            {playerRole && (
              <span className="text-xs font-medium text-flag">
                扮演：{playerRole}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 text-xs text-ink-soft">
            {pending && (
              <span className="animate-pulse text-flag">
                正在推进 {pending.label}
              </span>
            )}
            <span className="flex items-center gap-1.5">
              <span
                aria-hidden
                className={`size-1.5 shrink-0 rounded-full ${conn.dot}`}
              />
              {conn.text}
            </span>
            <AudioControls />
            <Link href="/" className={buttonClass("quiet", "xs")}>
              返回首页
            </Link>
          </div>
        </header>

        <div className="flex min-h-0 flex-1 gap-3 p-3 md:gap-4 md:p-4">
          <aside className="hidden w-60 shrink-0 overflow-y-auto md:block">
            <h2 className="mb-2.5 font-serif text-sm text-ink-soft">在场角色</h2>
            <RolePanel
              characters={characters}
              playableRoles={playableRoles}
              playerRole={playerRole}
            />
          </aside>

          <section className="flex min-h-0 flex-1 flex-col gap-3">
            <div className="relative min-h-0 flex-1 overflow-hidden rounded-lg border border-rule bg-panel backdrop-blur-sm">
              <div className="absolute inset-0 overflow-y-auto p-4">
                {messages.length === 0 ? (
                  <p className="text-sm text-ink-faint">等待剧情开始…</p>
                ) : (
                  <MessageStream
                    messages={messages}
                    playerRole={playerRole}
                    showSeq={process.env.NODE_ENV !== "production"}
                  />
                )}
              </div>
              <div className="pointer-events-none absolute inset-x-0 bottom-0 z-10 bg-gradient-to-t from-black/85 via-black/45 to-transparent px-4 pt-14 pb-4">
                <SubtitleTrack messages={messages} streams={streams} />
              </div>
            </div>

            <InteractionCard />
            <RollbackBar />
          </section>
        </div>
      </GameStage>
      <ToastHost />
    </main>
  );
}

export default function GamePage() {
  return (
    <Suspense
      fallback={
        <main
          data-surface="stage"
          className="flex flex-1 items-center justify-center bg-canvas p-8"
        >
          <Loading />
        </main>
      }
    >
      <GameContent />
    </Suspense>
  );
}
