import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";

/** 输入控件尺寸。尺寸与宽度都只由 prop / className 决定——类串拼接没有 twMerge，
 *  基类里若自带 `py-2`/`w-full`，调用方的 `py-1`/`w-52` 压不过它（同属性同优先级，
 *  胜负取决于生成顺序）。所以宽度不进基类，每个调用点自己写。 */
export type ControlSize = "sm" | "md";

const CONTROL_BASE = [
  "rounded-md border border-rule-strong bg-surface text-ink",
  "placeholder:text-ink-faint",
  "outline-none transition-colors",
  "focus:border-accent",
  "disabled:opacity-50",
].join(" ");

const CONTROL_SIZE: Record<ControlSize, string> = {
  sm: "px-2.5 py-1.5 text-sm",
  md: "px-3 py-2 text-base",
};

export function controlClass(size: ControlSize = "md", className = ""): string {
  return [CONTROL_BASE, CONTROL_SIZE[size], className].filter(Boolean).join(" ");
}

export function TextInput({
  controlSize = "md",
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { controlSize?: ControlSize }) {
  return <input className={controlClass(controlSize, className)} {...props} />;
}

export function TextArea({
  controlSize = "md",
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement> & { controlSize?: ControlSize }) {
  return <textarea className={controlClass(controlSize, className)} {...props} />;
}

export function Select({
  controlSize = "md",
  className = "",
  ...props
}: SelectHTMLAttributes<HTMLSelectElement> & { controlSize?: ControlSize }) {
  return <select className={controlClass(controlSize, className)} {...props} />;
}

/** 带标签的字段：标签在上，提示在下。
 *  标签**包住**控件（隐式关联），而不是用 htmlFor——调用方常忘了配对 id，
 *  而 `getByLabel` 这类无障碍查询一旦失去关联就查不到控件。 */
export function Field({
  label,
  hint,
  children,
  className = "",
}: {
  label: string;
  hint?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <label className={`flex flex-col gap-1.5 ${className}`}>
      <span className="text-sm font-medium text-ink-soft">{label}</span>
      {children}
      {hint && <span className="text-xs text-ink-faint">{hint}</span>}
    </label>
  );
}
