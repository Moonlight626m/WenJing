"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { AuthField } from "@/components/auth/auth-field";
import { FormError } from "@/components/auth/form-error";
import { Button, buttonClass } from "@/components/ui/button";
import { formatApiError, register } from "@/lib/api";
import { roleHome } from "@/lib/role-home";

type IdentifierKind = "email" | "phone";

export function RegisterForm() {
  const router = useRouter();
  const [kind, setKind] = useState<IdentifierKind>("email");
  const [identifier, setIdentifier] = useState("");
  const [nickname, setNickname] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setError(null);
    try {
      const trimmed = identifier.trim();
      const info = await register({
        email: kind === "email" ? trimmed : null,
        phone: kind === "phone" ? trimmed : null,
        nickname: nickname.trim(),
        password,
      });
      router.replace(roleHome(info.user.role));
      router.refresh();
    } catch (err) {
      setError(formatApiError(err));
      setPending(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="flex w-full flex-col gap-4">
      <div className="flex gap-2">
        {(["email", "phone"] as const).map((option) => (
          <button
            key={option}
            type="button"
            aria-pressed={kind === option}
            onClick={() => {
              setKind(option);
              setIdentifier("");
            }}
            className={buttonClass(kind === option ? "solid" : "outline", "xs")}
          >
            {option === "email" ? "用邮箱注册" : "用手机号注册"}
          </button>
        ))}
      </div>

      <AuthField
        label={kind === "email" ? "邮箱" : "手机号"}
        name="identifier"
        type={kind === "email" ? "email" : "tel"}
        value={identifier}
        onChange={setIdentifier}
        autoComplete={kind === "email" ? "email" : "tel"}
        required
      />
      <AuthField
        label="昵称"
        name="nickname"
        value={nickname}
        onChange={setNickname}
        maxLength={32}
        required
      />
      <AuthField
        label="密码（至少 8 位）"
        name="password"
        type="password"
        value={password}
        onChange={setPassword}
        autoComplete="new-password"
        minLength={8}
        required
      />

      <FormError message={error} />

      <Button type="submit" tone="solid" size="md" disabled={pending}>
        {pending ? "注册中…" : "注册并登录"}
      </Button>

      <p className="text-sm text-ink-soft">
        已有账号？
        <Link href="/login" className="ml-1 text-accent underline">
          登录
        </Link>
      </p>
    </form>
  );
}
