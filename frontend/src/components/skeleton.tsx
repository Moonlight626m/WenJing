/** 细脉动骨架条（全场通用加载占位）。 */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded bg-zinc-200/80 dark:bg-zinc-800 ${className}`}
    />
  );
}

/** 圆角卡片占位：一条标题条 + 若干文本行。 */
export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-zinc-200 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <Skeleton className="h-4 w-1/3" />
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={`h-3 ${i % 2 ? "w-5/6" : "w-2/3"}`} />
      ))}
    </div>
  );
}
