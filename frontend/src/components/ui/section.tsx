import type { ReactNode } from "react";

/**
 * 栏目标题：题在左、计数在右，其下一道界行贯通内容宽。
 * 界行承载结构（哪一段到哪一段），不作装饰。
 *
 * 计数渲染在 `<h2>` **内部**（靠 flex 推到右端），而不是作兄弟节点——
 * 否则按标题导航的读屏用户听不到「已发布 3 篇」里那个 3。
 */
export function SectionHeading({
  title,
  meta,
  action,
  className = "",
}: {
  title: ReactNode;
  meta?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={[
        "flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-rule pb-2",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <h2 className="flex flex-1 flex-wrap items-baseline justify-between gap-x-4 text-lg text-ink">
        <span>{title}</span>
        {meta != null && (
          <span className="font-mono text-xs text-ink-faint">{meta}</span>
        )}
      </h2>
      {action}
    </div>
  );
}

/** 版心：受保护区域的通用页栏——内容居中、天头地脚留白。 */
export function PageShell({
  children,
  width = "max-w-3xl",
  className = "",
}: {
  children: ReactNode;
  width?: string;
  className?: string;
}) {
  return (
    <main
      className={[
        "mx-auto flex w-full flex-1 flex-col gap-8 px-5 py-10 sm:px-8",
        width,
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      {children}
    </main>
  );
}
