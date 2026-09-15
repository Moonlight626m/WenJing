import { redirect } from "next/navigation";

import { AuthShell } from "@/components/auth/auth-shell";
import { RegisterForm } from "@/components/auth/register-form";
import { getCurrentUser } from "@/lib/auth-server";
import { roleHome } from "@/lib/role-home";

export const metadata = { title: "注册 · 文境" };

export default async function RegisterPage() {
  const user = await getCurrentUser();
  if (user) redirect(roleHome(user.role));

  return (
    <AuthShell title="注册文境" subtitle="注册即获得学生账号，可浏览并游玩公开剧本">
      <RegisterForm />
    </AuthShell>
  );
}
