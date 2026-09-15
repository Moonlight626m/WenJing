import { ProtectedShell } from "@/components/auth/protected-shell";
import { STUDENT_ROLES } from "@/lib/auth-server";

export default async function StudentLayout({
  children,
}: LayoutProps<"/student">) {
  return <ProtectedShell roles={STUDENT_ROLES}>{children}</ProtectedShell>;
}
