import type { ReactNode } from "react";

/**
 * 方章：状态标记。
 * 改用方角 + 发丝边（旧样式是圆角药丸），近于册页上的印记；
 * 朱砂（flag）专留给"在场"——正在生成、你演的角色、在途流。
 */
export type TagTone = "neutral" | "accent" | "flag" | "ok" | "warn" | "danger";

const TONES: Record<TagTone, string> = {
  neutral: "border-rule-strong text-ink-soft",
  accent: "border-accent/45 bg-accent-wash text-accent",
  flag: "border-flag/45 bg-flag-wash text-flag",
  ok: "border-ok/45 bg-ok-wash text-ok",
  warn: "border-warn/45 bg-warn-wash text-warn",
  danger: "border-danger/45 bg-danger-wash text-danger",
};

export function Tag({
  tone = "neutral",
  children,
  className = "",
  title,
}: {
  tone?: TagTone;
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <span
      title={title}
      className={[
        "inline-flex shrink-0 items-center rounded-sm border px-1.5 py-0.5 text-2xs leading-tight font-medium whitespace-nowrap",
        TONES[tone],
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </span>
  );
}
