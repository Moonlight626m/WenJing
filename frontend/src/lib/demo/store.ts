"use client";

import { useSyncExternalStore } from "react";
import { create } from "zustand";

/**
 * 演出模式自己的一点状态：拾到的句子、命运抉择的特效阶段、结局、暂停与回溯次数。
 * 游戏本身的状态（消息、阶段、交互点）仍在 gameStore，这里只放舞台之外的那一层。
 */
export interface CaughtQuote {
  text: string;
  note: string;
}

/** 命运抉择的三个阶段：没有 / 正在选（画面褪色）/ 刚选定（墨点溅开）。 */
export type FatePhase = "idle" | "choosing" | "splash";

interface DemoState {
  paused: boolean;
  fate: FatePhase;
  quotes: CaughtQuote[];
  /** 刚拾到、正在屏幕中央展示的那一句。 */
  catching: CaughtQuote | null;
  ending: string | null;
  rollbacks: number;
  /** 当前抉择允许自己写时，给演示者的几句现成的话。 */
  suggestions: string[];
  /** 已经走到过命运抉择，可以回到那里换一条路。 */
  canParallel: boolean;
  flags: Record<string, string>;
  /** 本局开演时间：结局卡算「这一局演了几分钟」。 */
  startedAt: number;
}

const INITIAL: DemoState = {
  paused: false,
  fate: "idle",
  quotes: [],
  catching: null,
  ending: null,
  rollbacks: 0,
  suggestions: [],
  canParallel: false,
  flags: {},
  startedAt: 0,
};

export const useDemoStore = create<DemoState>(() => ({ ...INITIAL }));

export function resetDemoStore() {
  useDemoStore.setState({ ...INITIAL, startedAt: Date.now() });
}

/** 已解锁的结局存在本机：书匣与结局图鉴据此显示「已解锁 n/3」。 */
function endingsKey(slug: string): string {
  return `wj-demo-endings:${slug}`;
}

export function loadUnlocked(slug: string): string[] {
  try {
    const raw = window.localStorage.getItem(endingsKey(slug));
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === "string") : [];
  } catch {
    return [];
  }
}

export function saveUnlocked(slug: string, ending: string): string[] {
  const next = Array.from(new Set([...loadUnlocked(slug), ending]));
  try {
    window.localStorage.setItem(endingsKey(slug), JSON.stringify(next));
  } catch {
    // 记不下来只是下次书匣上不显示解锁进度
  }
  return next;
}

export function clearUnlocked(slug: string) {
  try {
    window.localStorage.removeItem(endingsKey(slug));
  } catch {
    // 同上
  }
}

const noopSubscribe = () => () => {};

/** 某一卷已解锁几个结局。本机存储只在浏览器里读得到，服务端渲染时当 0。 */
export function useUnlockedCount(slug: string): number {
  return useSyncExternalStore(
    noopSubscribe,
    () => loadUnlocked(slug).length,
    () => 0
  );
}
