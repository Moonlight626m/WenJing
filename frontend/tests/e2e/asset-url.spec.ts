/**
 * 预签名 URL 缓存（#54）端到端。
 *
 * 覆盖 ADR-0005 §3「返回短时效预签名 URL；**前端按过期时间缓存**」——
 * 缓存按 `expires_at` 判活并留提前作废余量；`expires_at` 缺失/不可解析时按已过期处理
 * （宁可多签一次，也不用可能失效的地址）。
 *
 * 前置：无（纯函数断言，不起浏览器）。
 */
import { expect, test } from "@playwright/test";

import {
  ASSET_URL_EXPIRY_MARGIN_MS,
  putCachedAssetUrl,
  readCachedAssetUrl,
} from "../../src/lib/asset-url";

const NOW = Date.parse("2026-09-29T12:00:00Z");
const at = (ms: number) => new Date(NOW + ms).toISOString();

test.describe("#54 预签名 URL 缓存", () => {
  test("未缓存的资产 → null", () => {
    expect(readCachedAssetUrl("a-never-cached", NOW)).toBeNull();
  });

  test("有效期内命中缓存（不重复签名）", () => {
    putCachedAssetUrl("a-valid", "http://minio/x?sig=1", at(10 * 60_000));
    expect(readCachedAssetUrl("a-valid", NOW)).toBe("http://minio/x?sig=1");
  });

  test("临近过期（余量内）与已过期 → 失效", () => {
    putCachedAssetUrl("a-near", "http://minio/x?sig=2", at(ASSET_URL_EXPIRY_MARGIN_MS - 1));
    expect(readCachedAssetUrl("a-near", NOW)).toBeNull();
    putCachedAssetUrl("a-past", "http://minio/x?sig=3", at(-1000));
    expect(readCachedAssetUrl("a-past", NOW)).toBeNull();
  });

  test("expires_at 不可解析 → 按已过期处理", () => {
    putCachedAssetUrl("a-bad", "http://minio/x?sig=4", "not-a-date");
    expect(readCachedAssetUrl("a-bad", NOW)).toBeNull();
  });
});
