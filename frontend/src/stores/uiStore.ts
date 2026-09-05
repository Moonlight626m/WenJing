"use client";

import { create } from "zustand";

export type ToastKind = "info" | "error" | "success";

export interface ToastItem {
  id: number;
  kind: ToastKind;
  title: string;
  description?: string;
}

interface UiStore {
  toasts: ToastItem[];
  push: (toast: { kind: ToastKind; title: string; description?: string }) => void;
  dismiss: (id: number) => void;
}

let nextId = 1;

export const useUiStore = create<UiStore>((set) => ({
  toasts: [],
  push: (toast) =>
    set((state) => ({
      toasts: [...state.toasts, { id: nextId++, ...toast }].slice(-5),
    })),
  dismiss: (id) =>
    set((state) => ({ toasts: state.toasts.filter((t) => t.id !== id) })),
}));
