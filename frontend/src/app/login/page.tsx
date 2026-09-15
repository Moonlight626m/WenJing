import { redirect } from "next/navigation";

import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/components/auth/login-form";
import { getCurrentUser } from "@/lib/auth-server";
import { roleHome } from "@/lib/role-home";

export const metadata = { title: "登录 · 文境" };

export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) redirect(roleHome(user.role));

  return (
    <AuthShell title="登录文境" subtitle="教师创作剧本 · 学生游玩演绎">
      <LoginForm />
    </AuthShell>
  );
}
