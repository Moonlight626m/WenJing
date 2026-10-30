/**
 * 资产图片降级（#54）端到端。
 *
 * 覆盖验收：「缺失资产优雅降级」——详情页/审批面板图片位上的文案矩阵。
 * 判定顺序即语义优先级：资产未就绪 → 完全没有资产 → 有 ready 资产但取图失败；
 * 未就绪的槽位不得退化成「无图」（否则教师会以为该槽位本就不配图）。
 * 取图与预签名 URL 缓存（ADR-0005 §3）走真实请求，由页面验收覆盖，不在此断言。
 *
 * 前置：无（纯函数断言，不起浏览器）。
 */
import { expect, test } from "@playwright/test";

import { assetPlaceholder } from "../../src/components/asset-image";
import type { AssetRef } from "../../src/lib/contracts/types";

function ref(status: AssetRef["status"]): AssetRef {
  return { asset_id: "11111111-1111-1111-1111-111111111111", kind: "background", status };
}

test.describe("#54 资产图片降级", () => {
  for (const [status, expected] of [
    ["pending", "生成中…"],
    ["failed", "生成失败"],
  ] as const) {
    test(`资产 ${status} → 「${expected}」`, () => {
      expect(assetPlaceholder(ref(status), { failed: false })).toBe(expected);
      // 未就绪不得被 emptyLabel 覆盖成「无图」
      expect(
        assetPlaceholder(ref(status), {
          failed: false,
          emptyLabel: "无图（纯文本游玩）",
        })
      ).toBe(expected);
    });
  }

  test("完全无资产 → 缺省「无图」，调用方可覆盖文案", () => {
    expect(assetPlaceholder(null, { failed: false })).toBe("无图");
    expect(assetPlaceholder(undefined, { failed: false })).toBe("无图");
    expect(
      assetPlaceholder(null, { failed: false, emptyLabel: "无图（纯文本游玩）" })
    ).toBe("无图（纯文本游玩）");
  });

  test("ready 资产取图失败/未返回 → 如实降级", () => {
    expect(assetPlaceholder(ref("ready"), { failed: true })).toBe("图片暂不可用");
    expect(assetPlaceholder(ref("ready"), { failed: false })).toBe("加载中…");
  });
});
