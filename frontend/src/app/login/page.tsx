import { redirect } from "next/navigation";

import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/components/auth/login-form";
import { getCurrentUser } from "@/lib/auth-server";
import { roleHome } from "@/lib/role-home";

export const metadata = { title: "登录" };

export default async function LoginPage() {
  const user = await getCurrentUser();
  if (user) redirect(roleHome(user.role));

  return (
    <AuthShell title="登录文境" subtitle="进入课文，成为其中的人">
      <LoginForm />
    </AuthShell>
  );
}
