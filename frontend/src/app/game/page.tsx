"use client";

import { Suspense, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";

import { useGameChannel } from "@/lib/ws";
import { getScriptDetail, getStatus } from "@/lib/api";
import { loadRecents, upsertRecent } from "@/lib/session-cache";
import { useGameStore } from "@/stores/gameStore";
import { useUiStore } from "@/stores/uiStore";
import { GameScreen } from "@/components/game-screen";
import { ToastHost } from "@/components/toast-host";
import { buttonClass } from "@/components/ui/button";
import { Loading } from "@/components/ui/states";

function GameContent() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("id");

  const scriptId = useGameStore((s) => s.scriptId);
  const resetSession = useGameStore((s) => s.resetSession);
  const setStatusInfo = useGameStore((s) => s.setStatusInfo);
  const setScriptInfo = useGameStore((s) => s.setScriptInfo);

  const push = useUiStore((s) => s.push);

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

  // 角色档案（立绘、头像、小传）只在剧本包里：按 session_init 带来的剧本补拉一次。
  // 选角页已经放进 store 的那份也会被同一份覆盖，顺带纠正上一局残留的角色表。
  // 拉不到就退化成只有名字的角色，不影响游玩。
  useEffect(() => {
    if (scriptId === null) return;
    let cancelled = false;
    getScriptDetail(scriptId)
      .then((detail) => {
        if (!cancelled && detail.package) setScriptInfo(detail.package);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [scriptId, setScriptInfo]);

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

  return (
    <main
      data-surface="stage"
      className="flex h-screen w-full flex-col overflow-hidden bg-canvas"
    >
      <GameScreen />
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
