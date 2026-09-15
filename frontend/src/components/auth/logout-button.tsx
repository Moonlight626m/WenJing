"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { ApiError, logout } from "@/lib/api";

export function LogoutButton() {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function handleLogout() {
    if (pending) return;
    setPending(true);
    try {
      await logout();
    } catch (err) {
      // 会话已失效（401）等价于登出成功；其它错误提示后仍回登录页。
      if (!(err instanceof ApiError && err.status === 401)) {
        console.error("logout failed", err);
      }
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      disabled={pending}
      className="rounded-full border border-zinc-300 px-3 py-1 text-xs text-zinc-600 transition-colors hover:bg-zinc-100 disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-800"
    >
      {pending ? "登出中…" : "登出"}
    </button>
  );
}
