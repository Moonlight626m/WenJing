"use client";

import { useEffect } from "react";

import { useUiStore, type ToastItem } from "@/stores/uiStore";

/** 提示条：发丝边框 + 左侧一道音色线，不做圆角卡片堆叠。 */
const TONES: Record<ToastItem["kind"], string> = {
  info: "bg-rule-strong",
  success: "bg-ok",
  error: "bg-danger",
};

function Toast({ toast }: { toast: ToastItem }) {
  const dismiss = useUiStore((s) => s.dismiss);
  useEffect(() => {
    const timer = setTimeout(() => dismiss(toast.id), 6000);
    return () => clearTimeout(timer);
  }, [toast.id, dismiss]);
  return (
    <div
      role="status"
      className="pointer-events-auto relative max-w-sm overflow-hidden rounded-md border border-rule bg-surface py-3 pr-4 pl-5 text-sm shadow-[var(--shadow-lift)]"
    >
      <span aria-hidden className={`absolute inset-y-0 left-0 w-0.5 ${TONES[toast.kind]}`} />
      <div className="font-medium text-ink">{toast.title}</div>
      {toast.description && (
        <div className="measure mt-1 text-xs whitespace-pre-wrap text-ink-soft">
          {toast.description}
        </div>
      )}
    </div>
  );
}

export function ToastHost() {
  const toasts = useUiStore((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed right-4 bottom-4 z-50 flex flex-col gap-2"
    >
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} />
      ))}
    </div>
  );
}
