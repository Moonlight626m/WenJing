"use client";

import { useEffect } from "react";

import { useUiStore, type ToastItem } from "@/stores/uiStore";

const STYLES: Record<ToastItem["kind"], string> = {
  info: "border-zinc-300 bg-white text-zinc-800 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-200",
  success:
    "border-emerald-300 bg-emerald-50 text-emerald-800 dark:border-emerald-700 dark:bg-emerald-950 dark:text-emerald-200",
  error:
    "border-red-300 bg-red-50 text-red-800 dark:border-red-800 dark:bg-red-950 dark:text-red-200",
};

function Toast({ toast }: { toast: ToastItem }) {
  const dismiss = useUiStore((s) => s.dismiss);
  useEffect(() => {
    const timer = setTimeout(() => dismiss(toast.id), 6000);
    return () => clearTimeout(timer);
  }, [toast.id, dismiss]);
  return (
    <div
      className={`pointer-events-auto max-w-sm rounded-lg border px-4 py-3 text-sm shadow-md ${STYLES[toast.kind]}`}
    >
      <div className="font-medium">{toast.title}</div>
      {toast.description && (
        <div className="mt-1 whitespace-pre-wrap opacity-80">{toast.description}</div>
      )}
    </div>
  );
}

export function ToastHost() {
  const toasts = useUiStore((s) => s.toasts);
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none fixed right-4 bottom-4 z-50 flex flex-col gap-2">
      {toasts.map((t) => (
        <Toast key={t.id} toast={t} />
      ))}
    </div>
  );
}
