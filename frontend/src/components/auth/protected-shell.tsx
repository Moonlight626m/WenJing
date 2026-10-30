import type { ReactNode } from "react";

import { AppHeader } from "@/components/auth/app-header";
import { requireRole } from "@/lib/auth-server";
import type { UserRole } from "@/lib/contracts/types";

/** 受保护区域的统一外壳：角色守卫 + 顶栏 + 内容。 */
export async function ProtectedShell({
  roles,
  children,
}: {
  roles: readonly UserRole[];
  children: ReactNode;
}) {
  const user = await requireRole(...roles);
  return (
    <div className="flex min-h-full flex-1 flex-col">
      <AppHeader user={user} />
      <div className="flex flex-1 flex-col">{children}</div>
    </div>
  );
}
