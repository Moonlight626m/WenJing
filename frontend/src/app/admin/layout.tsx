import { ProtectedShell } from "@/components/auth/protected-shell";
import { ADMIN_ROLES } from "@/lib/auth-server";

export default async function AdminLayout({ children }: LayoutProps<"/admin">) {
  return <ProtectedShell roles={ADMIN_ROLES}>{children}</ProtectedShell>;
}
