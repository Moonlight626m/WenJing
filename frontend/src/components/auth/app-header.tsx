import Link from "next/link";

import { LogoutButton } from "@/components/auth/logout-button";
import { Seal } from "@/components/ui/seal";
import { Tag } from "@/components/ui/tag";
import type { UserPublic } from "@/lib/contracts/types";
import { roleHome, roleLabel } from "@/lib/role-home";

/** 受保护区域的通用顶栏：品牌入口 + 当前用户 + 登出。 */
export function AppHeader({ user }: { user: UserPublic }) {
  return (
    <header className="flex items-center justify-between gap-4 border-b border-rule bg-surface px-5 py-2.5 sm:px-8">
      <Link
        href={roleHome(user.role)}
        className="flex items-center gap-2.5 focus-ring"
      >
        <Seal className="text-sm" />
        <span className="font-serif text-lg font-semibold tracking-[0.18em]">
          文境
        </span>
      </Link>
      <div className="flex items-center gap-3">
        <span className="text-sm text-ink-soft">{user.nickname}</span>
        <Tag>{roleLabel(user.role)}</Tag>
        <LogoutButton />
      </div>
    </header>
  );
}
