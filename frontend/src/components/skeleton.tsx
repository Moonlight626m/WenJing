/** 细脉动骨架条（全场通用加载占位）。 */
export function Skeleton({ className = "" }: { className?: string }) {
  return (
    <div
      aria-hidden
      className={`animate-pulse rounded-sm bg-sunken ${className}`}
    />
  );
}

/** 卡片占位：一条标题条 + 若干文本行。与真实卡片的版式对齐，避免加载完成时跳动。 */
export function SkeletonCard({ lines = 3 }: { lines?: number }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-rule bg-surface p-4">
      <Skeleton className="h-4 w-1/3" />
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton key={i} className={`h-3 ${i % 2 ? "w-5/6" : "w-2/3"}`} />
      ))}
    </div>
  );
}
