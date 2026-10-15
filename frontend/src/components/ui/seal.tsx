/**
 * 白文印：品牌标记。
 *
 * 印文取**学科**而不是产品名——印在调用处总是紧挨着「文境」两个大字，
 * 再钤一遍同样的字就成了回声；刻「语文」既点明题材，也补了产品名没说的事。
 * 朱砂一方、字以纸色反白，是全站唯一处「朱砂不只表示在场」的地方。
 */
export function Seal({ className = "" }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={[
        "inline-grid shrink-0 place-items-center rounded-sm bg-flag px-2 py-1.5",
        "font-serif text-base leading-none tracking-[0.08em] text-canvas select-none",
        className,
      ]
        .filter(Boolean)
        .join(" ")}
    >
      语文
    </span>
  );
}
