import type { ButtonHTMLAttributes } from "react";

/**
 * 按钮音色。accent=靛青主操作，solid=墨色重操作，outline=次级，quiet=文字链。
 * glow=舞台上的主操作（发送、进入续写），青碧到泥金的渐变底加一圈辉光；册面不用。
 */
export type ButtonTone =
  | "accent"
  | "glow"
  | "solid"
  | "outline"
  | "ok"
  | "danger"
  | "quiet";
export type ButtonSize = "xs" | "sm" | "md";

const TONES: Record<ButtonTone, string> = {
  accent:
    "border border-transparent bg-accent text-accent-ink hover:brightness-110",
  glow:
    "border border-transparent bg-linear-110 from-glow-jade to-glow-gold text-accent-ink shadow-[0_0_18px_-6px_var(--wj-glow-jade)] hover:brightness-110 hover:shadow-[0_0_26px_-4px_var(--wj-glow-jade)]",
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
    "inline-flex shrink-0 items-center justify-center gap-1.5 font-medium",
    // glow 只出现在舞台的毛玻璃浮层里，跟着浮层用大一档的圆角
    tone === "glow" ? "rounded-xl" : "rounded-md",
    "transition-[filter,background-color,border-color,color,box-shadow] duration-150",
    "disabled:pointer-events-none disabled:opacity-45",
    tone === "quiet" ? QUIET_SIZES[size] : SIZES[size],
    TONES[tone],
    className,
  ]
    .filter(Boolean)
    .join(" ");
}

/**
 * 舞台上的圆形图标按钮（毛玻璃底）。图标不带语义，可读名必须由调用方给 aria-label。
 * `dim` 用于「关着」的开关态（如静音中）；字色走参数而不是让调用方再叠一个 text-*，
 * 因为没有 twMerge，两个字色类同时在场时谁赢看生成顺序。
 */
export function iconButtonClass(dim = false, className = ""): string {
  return [
    "inline-grid size-8 shrink-0 place-items-center rounded-full text-base",
    "border border-glass-edge bg-glass backdrop-blur-md",
    dim ? "text-ink-faint" : "text-ink-soft",
    "transition-[color,box-shadow] duration-150",
    "hover:text-ink hover:shadow-[0_0_16px_-4px_var(--wj-glow-jade)]",
    "disabled:pointer-events-none disabled:opacity-45",
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
