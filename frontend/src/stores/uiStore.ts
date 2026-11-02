"use client";

import { create } from "zustand";

import { useMediaQuery } from "@/lib/use-media-query";

export type ToastKind = "info" | "error" | "success";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  description?: string;
}

/**
 * 舞台特效档位。full=粒子、视差、推镜、墨晕转场全开；lite=只留必要的过渡，
 * 毛玻璃也换成不模糊的实底——学校机房和投影电脑跑不动大面积 backdrop-filter。
 */
export type EffectsLevel = "full" | "lite";

const EFFECTS_KEY = "wj-effects";

/** 读本机记住的档位；无痕窗口、禁用存储时读不到，按 full 处理。 */
function loadEffects(): EffectsLevel {
  try {
    return window.localStorage.getItem(EFFECTS_KEY) === "lite" ? "lite" : "full";
  } catch {
    return "full";
  }
}

function saveEffects(level: EffectsLevel) {
  try {
    window.localStorage.setItem(EFFECTS_KEY, level);
  } catch {
    // 存不下只影响下次打开时的默认值，不影响本次
  }
}

interface UiStore {
  toasts: ToastItem[];
  push: (toast: { kind: ToastKind; title: string; description?: string }) => void;
  dismiss: (id: number) => void;
  /** 用户选的特效档位；`null` 表示还没从本机读过（SSR 与首帧）。 */
  effects: EffectsLevel | null;
  hydrateEffects: () => void;
  setEffects: (level: EffectsLevel) => void;
}

let nextId = 1;

export const useUiStore = create<UiStore>((set, get) => ({
  toasts: [],
  push: (toast) =>
    set((state) => ({
      toasts: [...state.toasts, { id: nextId++, ...toast }].slice(-5),
    })),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
  effects: null,
  hydrateEffects: () => {
    if (get().effects === null) set({ effects: loadEffects() });
  },
  setEffects: (level) => {
    saveEffects(level);
    set({ effects: level });
  },
}));

/**
 * 实际生效的特效档位：系统开了「减少动态效果」一律按 lite，否则听用户的。
 * 未从本机读出档位前按 lite 渲染——宁可首帧少一点特效，也不要先放粒子再撤掉。
 */
export function useEffectsLevel(): EffectsLevel {
  const chosen = useUiStore((s) => s.effects);
  const reduced = useMediaQuery("(prefers-reduced-motion: reduce)");
  if (reduced) return "lite";
  return chosen ?? "lite";
}
