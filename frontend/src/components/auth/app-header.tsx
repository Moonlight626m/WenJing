import Link from "next/link";

import { LogoutButton } from "@/components/auth/logout-button";
import type { UserPublic } from "@/lib/contracts/types";
import { roleHome, roleLabel } from "@/lib/role-home";

/** 受保护区域的通用顶栏：品牌入口 + 当前用户 + 登出。 */
export function AppHeader({ user }: { user: UserPublic }) {
  return (
    <header className="flex items-center justify-between border-b border-zinc-200 bg-white px-6 py-3 dark:border-zinc-800 dark:bg-zinc-900">
      <Link href={roleHome(user.role)} className="text-lg font-semibold tracking-tight">
        文境
      </Link>
      <div className="flex items-center gap-3 text-xs text-zinc-500 dark:text-zinc-400">
        <span>
          {user.nickname} · {roleLabel(user.role)}
        </span>
        <LogoutButton />
      </div>
    </header>
  );
}
