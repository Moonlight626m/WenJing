"use client";

import { useGameStore } from "@/stores/gameStore";

/** 交互卡与侧栏操作共用的「此刻不能提交」判定：等待引擎、断线、世界重建中。 */
export function useInteractionBusy(): boolean {
  const pending = useGameStore((s) => s.pending);
  const connection = useGameStore((s) => s.connection);
  const sessionInitialized = useGameStore((s) => s.sessionInitialized);
  return pending !== null || connection !== "connected" || !sessionInitialized;
}
