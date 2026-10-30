"use client";

import { useEffect, useState } from "react";

import { fetchAssetUrl } from "@/lib/api";
import type { AssetRef } from "@/lib/contracts/types";

/**
 * 预签名 URL 缓存（ADR-0005 §3「返回短时效预签名 URL；前端按过期时间缓存」）。
 *
 * 进程内、按 `asset_id` 去重：同一资产在一页里挂多处（详情页头像 + 审批缩略图）
 * 只签一次。URL 含凭证 → 不落 localStorage。留 `ASSET_URL_EXPIRY_MARGIN_MS` 余量
 * 提前作废，避免拿到临界过期的地址。
 */
const URL_CACHE = new Map<string, { url: string; expiresAt: number }>();
export const ASSET_URL_EXPIRY_MARGIN_MS = 60_000;

/** 命中且未临近过期才返回；过期/不可解析的条目顺手清掉。 */
export function readCachedAssetUrl(assetId: string, now = Date.now()): string | null {
  const hit = URL_CACHE.get(assetId);
  if (!hit) return null;
  // expires_at 不可解析时按已过期处理（宁可多签一次，也不用可能失效的地址）
  if (!Number.isFinite(hit.expiresAt) || hit.expiresAt - ASSET_URL_EXPIRY_MARGIN_MS <= now) {
    URL_CACHE.delete(assetId);
    return null;
  }
  return hit.url;
}

export function putCachedAssetUrl(assetId: string, url: string, expiresAt: string): void {
  URL_CACHE.set(assetId, { url, expiresAt: Date.parse(expiresAt) });
}

/**
 * 稳定资产引用 → 预签名 URL（游玩页背景 #53、详情页与配图审批 #54 共用）。
 *
 * 复位键用 `asset_id` 这一稳定标量：绑定的对象每次渲染都可能是新字面量
 * （审批面板里由「上传」意图合成的 AssetRef），拿对象身份判定会每次渲染都
 * 判不等 —— 既反复重置状态，也反复发起取图请求，直至 React 抛渲染次数超限。
 */
export function useAssetUrl(asset: AssetRef | null | undefined): {
  url: string | null;
  failed: boolean;
} {
  const assetId = asset && asset.status === "ready" ? asset.asset_id : null;
  // 渲染期读缓存是纯读；命中即不再发起签名请求（缓存在 effect 内写入）
  const cached = assetId ? readCachedAssetUrl(assetId) : null;
  const [fetched, setFetched] = useState<{ assetId: string; url: string } | null>(
    null
  );
  const [failed, setFailed] = useState(false);
  // 渲染期间重置派生状态（React「props 变化时调整 state」模式）
  const [lastId, setLastId] = useState<string | null>(assetId);
  if (assetId !== lastId) {
    setLastId(assetId);
    setFetched(null);
    setFailed(false);
  }

  useEffect(() => {
    let active = true;
    if (!assetId || cached) return;
    fetchAssetUrl(assetId)
      .then((res) => {
        putCachedAssetUrl(assetId, res.url, res.expires_at);
        if (active) setFetched({ assetId, url: res.url });
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
    };
  }, [assetId, cached]);

  return {
    url: fetched && fetched.assetId === assetId ? fetched.url : cached,
    failed,
  };
}
