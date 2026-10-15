import type { ButtonHTMLAttributes } from "react";

/** 按钮音色。accent=靛青主操作，solid=墨色重操作，outline=次级，quiet=文字链。 */
export type ButtonTone =
  | "accent"
  | "solid"
  | "outline"
  | "ok"
  | "danger"
  | "quiet";
export type ButtonSize = "xs" | "sm" | "md";

const TONES: Record<ButtonTone, string> = {
  accent:
    "border border-transparent bg-accent text-accent-ink hover:brightness-110",
  solid: "border border-transparent bg-ink text-canvas hover:brightness-110",
  outline: "border border-rule-strong bg-surface text-ink hover:bg-sunken",
  ok: "border border-transparent bg-ok text-canvas hover:brightness-110",
  danger:
    "border border-danger/50 bg-transparent text-danger hover:bg-danger-wash",
  quiet:
    "border border-transparent bg-transparent px-0 text-accent hover:underline",
};

const SIZES: Record<ButtonSize, string> = {
  xs: "px-2.5 py-1 text-xs",
  sm: "px-3 py-1.5 text-sm",
  md: "px-4 py-2 text-base",
};

const QUIET_SIZES: Record<ButtonSize, string> = {
  xs: "py-0 text-xs",
  sm: "py-0 text-sm",
  md: "py-0 text-base",
};

/** 供 Link 等非 button 元素复用同一套外观。 */
export function buttonClass(
  tone: ButtonTone = "outline",
  size: ButtonSize = "sm",
  className = ""
): string {
  return [
    "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-md font-medium",
    "transition-[filter,background-color,border-color,color] duration-150",
    "disabled:pointer-events-none disabled:opacity-45",
    tone === "quiet" ? QUIET_SIZES[size] : SIZES[size],
    TONES[tone],
    className,
  ]
    .filter(Boolean)
    .join(" ");
}

export function Button({
  tone = "outline",
  size = "sm",
  className,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  tone?: ButtonTone;
  size?: ButtonSize;
}) {
  return <button className={buttonClass(tone, size, className)} {...props} />;
}
