"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AuthField } from "@/components/auth/auth-field";
import { FormError } from "@/components/auth/form-error";
import { Button } from "@/components/ui/button";
import { formatApiError, login } from "@/lib/api";
import { roleHome } from "@/lib/role-home";

export function LoginForm() {
  const router = useRouter();
  const [identifier, setIdentifier] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const info = await login({ identifier, password });
      router.replace(roleHome(info.user.role));
      router.refresh();
    } catch (err) {
      setError(formatApiError(err));
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full flex-col gap-4">
      <AuthField
        label="邮箱或手机号"
        name="identifier"
        value={identifier}
        onChange={setIdentifier}
        autoComplete="username"
        required
      />
      <AuthField
        label="密码"
        name="password"
        type="password"
        value={password}
        onChange={setPassword}
        autoComplete="current-password"
        required
      />

      <FormError message={error} />

      <Button type="submit" tone="solid" size="md" disabled={pending}>
        {pending ? "登录中…" : "登录"}
      </Button>

      <p className="text-sm text-ink-soft">
        还没有账号？
        <Link href="/register" className="ml-1 text-accent underline">
          注册
        </Link>
      </p>
    </form>
  );
}
