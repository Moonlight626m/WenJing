import { ProtectedShell } from "@/components/auth/protected-shell";
import { TEACHER_ROLES } from "@/lib/auth-server";

export default async function TeacherLayout({
  children,
}: LayoutProps<"/teacher">) {
  return <ProtectedShell roles={TEACHER_ROLES}>{children}</ProtectedShell>;
}
