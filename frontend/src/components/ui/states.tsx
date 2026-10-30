import type { ReactNode } from "react";

/** 空态：说明情况 + 给出下一步，不做情绪渲染。 */
export function Empty({
  children,
  action,
  className = "",
}: {
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={[
        "flex flex-col items-start gap-3 rounded-lg border border-dashed border-rule-strong bg-surface/60 px-5 py-6",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <p className="measure text-sm text-ink-soft">{children}</p>
      {action}
    </div>
  );
}

/** 行内加载态：文字 + 一枚旋转的墨点。 */
export function Loading({ label = "加载中…" }: { label?: string }) {
  return (
    <p
      role="status"
      className="flex items-center gap-2 text-sm text-ink-faint"
    >
      <Spinner />
      {label}
    </p>
  );
}

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={[
        "inline-block size-3 shrink-0 animate-spin rounded-full border-[1.5px] border-current border-t-transparent",
        className,
      ].join(" ")}
    />
  );
}
