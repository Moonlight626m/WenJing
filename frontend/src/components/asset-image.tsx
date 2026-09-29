"use client";

import { useAssetUrl } from "@/lib/asset-url";
import type { AssetRef } from "@/lib/contracts/types";

/** 图片位默认底色：详情页各槽位共用（本仓库无 twMerge，调用方要换色就整串覆盖）。 */
export const ASSET_IMAGE_BG = "bg-zinc-100 dark:bg-zinc-800";

/**
 * 图片位上的占位文案（#54 验收「缺失资产优雅降级」）。
 *
 * 判定顺序即语义优先级：资产未就绪（生成中/生成失败）→ 完全没有资产（用调用方的
 * 「无图」文案）→ 有 ready 资产但取图失败。未就绪的槽位**不能**退化成「无图」：
 * 那会让教师以为该槽位本来就不配图。
 */
export function assetPlaceholder(
  asset: AssetRef | null | undefined,
  { failed, emptyLabel }: { failed: boolean; emptyLabel?: string }
): string {
  if (!asset) return emptyLabel ?? "无图";
  if (asset.status === "pending") return "生成中…";
  if (asset.status === "failed") return "生成失败";
  return failed ? "图片暂不可用" : "加载中…";
}

/**
 * 资产图片（#54）：资产缺失 / 生成中 / 生成失败 / 取图失败一律降级为占位文案，
 * 不阻塞页面、不出现破图。取图与缓存见 `useAssetUrl`。
 */
export function AssetImage({
  asset,
  alt,
  className = `aspect-video w-full rounded ${ASSET_IMAGE_BG}`,
  emptyLabel,
  placeholderClassName = "text-xs text-zinc-400",
}: {
  asset: AssetRef | null | undefined;
  alt: string;
  /** 外层尺寸/底色类（宽高、圆角、底色都只由调用方决定，避免同类属性打架）。 */
  className?: string;
  /** 完全没有资产（`asset` 为空）时的占位文案；缺省「无图」。 */
  emptyLabel?: string;
  /** 占位文案的字体与颜色。 */
  placeholderClassName?: string;
}) {
  const { url, failed } = useAssetUrl(asset);

  return (
    <div className={`overflow-hidden ${className}`}>
      {url ? (
        // 预签名 URL 短时效、含凭证参数，仅当前视图使用
        // eslint-disable-next-line @next/next/no-img-element
        <img src={url} alt={alt} className="h-full w-full object-cover" />
      ) : (
        <div
          className={`flex h-full w-full items-center justify-center px-1 text-center ${placeholderClassName}`}
        >
          {assetPlaceholder(asset, { failed, emptyLabel })}
        </div>
      )}
    </div>
  );
}
