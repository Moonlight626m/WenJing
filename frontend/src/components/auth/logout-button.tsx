"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ApiError, logout } from "@/lib/api";
import { logger } from "@/lib/logger";

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
        logger.error("登出失败", err);
      }
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <Button tone="outline" size="xs" onClick={handleLogout} disabled={pending}>
      {pending ? "登出中…" : "登出"}
    </Button>
  );
}
