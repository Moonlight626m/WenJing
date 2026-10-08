/**
 * 运行期配图就绪消息（#56）端到端。
 *
 * 覆盖 ADR-0005 §5「命令之外的领域事件」在前端一侧的规则：`asset_ready` 是
 * **命令外**事件，不是命令响应——不进消息流、不结算 pending，只在场景仍匹配时
 * 换掉当前背景。
 *
 * 前置：无（纯函数断言，不起浏览器）。这里断言的是 store 里那段判定的纯函数入口，
 * 避免为了测一条消息而拉起整个游玩页。
 */
import { expect, test } from "@playwright/test";

import type { AssetRef } from "../../src/lib/contracts/types";
import { applyAssetReady } from "../../src/stores/gameStore";

const ASSET: AssetRef = {
  asset_id: "11111111-1111-1111-1111-111111111111",
  kind: "background",
  status: "ready",
};

test.describe("#56 运行期配图就绪", () => {
  test("场景匹配 → 换掉当前背景", () => {
    const next = applyAssetReady(
      { sceneKey: "scene:2", currentAsset: null },
      { scene_key: "scene:2", current_asset: ASSET }
    );
    expect(next).toEqual({ currentAsset: ASSET });
  });

  test("场景不匹配（玩家已走开）→ 丢弃，不闪回上一幕", () => {
    const next = applyAssetReady(
      { sceneKey: "scene:3", currentAsset: null },
      { scene_key: "scene:2", current_asset: ASSET }
    );
    expect(next).toBeNull();
  });

  test("场景仍匹配 → 覆盖已有的旧背景（同场景重生成/替换）", () => {
    const older = { ...ASSET, asset_id: "22222222-2222-2222-2222-222222222222" };
    const next = applyAssetReady(
      { sceneKey: "scene:2", currentAsset: older },
      { scene_key: "scene:2", current_asset: ASSET }
    );
    expect(next?.currentAsset.asset_id).toBe(ASSET.asset_id);
  });

  test("载荷缺 scene_key 或 current_asset → 丢弃", () => {
    const state = { sceneKey: "scene:2", currentAsset: null };
    expect(applyAssetReady(state, { current_asset: ASSET })).toBeNull();
    expect(applyAssetReady(state, { scene_key: "scene:2" })).toBeNull();
    expect(applyAssetReady(state, { scene_key: "scene:2", current_asset: null })).toBeNull();
    expect(applyAssetReady(state, {})).toBeNull();
  });

  test("当前尚无场景（未开播）→ 丢弃", () => {
    expect(
      applyAssetReady({ sceneKey: null, currentAsset: null }, { scene_key: "scene:1", current_asset: ASSET })
    ).toBeNull();
  });
});
