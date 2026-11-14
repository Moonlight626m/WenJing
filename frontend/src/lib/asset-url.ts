"use client";

import { useEffect, useState, useSyncExternalStore } from "react";

import { fetchAssetUrl } from "@/lib/api";
import type { AssetRef, AssetUrlResponse } from "@/lib/contracts/types";

/**
 * 预签名 URL 缓存（ADR-0005 §3「返回短时效预签名 URL；前端按过期时间缓存」）。
 *
 * 进程内、按 `asset_id` 去重：同一资产在一页里挂多处（详情页头像 + 审批缩略图）
 * 只签一次。URL 含凭证 → 不落 localStorage。留 `ASSET_URL_EXPIRY_MARGIN_MS` 余量
 * 提前作废，避免拿到临界过期的地址。
 *
 * 并发的挂载点（侧栏头像组、立绘、角色卡会同时挂同一张图）合并成一次请求；
 * 取图失败的资产（库里根本没有这一行）记一段冷却，期间挂载直接按失败渲染，
 * 冷却结束再试一次——否则每次重挂都往服务端打一发 404。
 */
const URL_CACHE = new Map<string, { url: string; expiresAt: number }>();
const IN_FLIGHT = new Map<string, Promise<AssetUrlResponse>>();
/** 失败资产的解禁时间：存在即表示当前处于冷却期。 */
const FAILED = new Map<string, number>();
export const ASSET_URL_EXPIRY_MARGIN_MS = 60_000;
/** 取图失败后的冷却时间。 */
const FAILED_RETRY_MS = 30_000;

/**
 * 失败表是模块级状态，组件要跟着它重渲（否则冷却期内会一直显示「加载中…」）。
 * 用版本号作快照：数字是纯值，`Date.now()` 这类不纯读取只发生在事件回调里。
 */
let failureVersion = 0;
const failureListeners = new Set<() => void>();

function bumpFailures(): void {
  failureVersion += 1;
  for (const listener of failureListeners) listener();
}

function noteFailure(assetId: string): void {
  FAILED.set(assetId, Date.now() + FAILED_RETRY_MS);
  bumpFailures();
  // 冷却结束后再通知一次：仍挂载的图片位会重新发起取图，而不是永远停在失败态
  setTimeout(() => {
    if (!FAILED.delete(assetId)) return;
    bumpFailures();
  }, FAILED_RETRY_MS);
}

function noteSuccess(assetId: string): void {
  if (!FAILED.delete(assetId)) return;
  bumpFailures();
}

function subscribeFailures(listener: () => void): () => void {
  failureListeners.add(listener);
  return () => failureListeners.delete(listener);
}

const getFailureVersion = () => failureVersion;
const serverFailureVersion = () => 0;

/** 命中且未临近过期才返回；**纯读**，清理交给下一次写入覆盖。 */
export function readCachedAssetUrl(assetId: string, now = Date.now()): string | null {
  const hit = URL_CACHE.get(assetId);
  if (!hit) return null;
  // expires_at 不可解析时按已过期处理（宁可多签一次，也不用可能失效的地址）
  if (!Number.isFinite(hit.expiresAt) || hit.expiresAt - ASSET_URL_EXPIRY_MARGIN_MS <= now) {
    return null;
  }
  return hit.url;
}

export function putCachedAssetUrl(assetId: string, url: string, expiresAt: string): void {
  URL_CACHE.set(assetId, { url, expiresAt: Date.parse(expiresAt) });
}

/** 同一资产的并发取图合并成一次请求。 */
function fetchAssetUrlShared(assetId: string): Promise<AssetUrlResponse> {
  const existing = IN_FLIGHT.get(assetId);
  if (existing) return existing;
  const request = fetchAssetUrl(assetId)
    .then((res) => {
      putCachedAssetUrl(assetId, res.url, res.expires_at);
      noteSuccess(assetId);
      return res;
    })
    .catch((error: unknown) => {
      noteFailure(assetId);
      throw error;
    })
    .finally(() => {
      IN_FLIGHT.delete(assetId);
    });
  IN_FLIGHT.set(assetId, request);
  return request;
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
  useSyncExternalStore(subscribeFailures, getFailureVersion, serverFailureVersion);
  const failed = assetId !== null && FAILED.has(assetId);
  // 渲染期间重置派生 state（React「props 变化时调整 state」模式）
  const [lastId, setLastId] = useState<string | null>(assetId);
  if (assetId !== lastId) {
    setLastId(assetId);
    setFetched(null);
  }

  useEffect(() => {
    let active = true;
    if (!assetId || cached || failed) return;
    fetchAssetUrlShared(assetId)
      .then((res) => {
        if (active) setFetched({ assetId, url: res.url });
      })
      .catch(() => {
        // 失败状态由模块表的版本号驱动，这里不重复记
      });
    return () => {
      active = false;
    };
  }, [assetId, cached, failed]);

  return {
    url: fetched && fetched.assetId === assetId ? fetched.url : cached,
    failed,
  };
}
