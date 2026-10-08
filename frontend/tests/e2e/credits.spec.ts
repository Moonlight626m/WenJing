/**
 * 来源/许可展示（#51）端到端。
 *
 * 覆盖验收：「许可白名单与署名规则有测试」的前端镜像侧——
 * `requiresAttribution`（labels.ts）镜像后端 `evaluate_license`
 * （backend/app/domain/game/image_review.py，权威测试
 * backend/tests/test_image_review.py::test_evaluate_license 参数化矩阵）。
 * **两侧用例清单需同步维护**：本矩阵是后端矩阵的镜像超集（含空串），
 * 改任一侧的许可 token 语义时必须同时改另一侧——无跨语言单源机制，
 * 靠这条注释与镜像矩阵对齐。
 * 「学生端不破坏游玩沉浸」由折叠 <details> 保证（默认收起）。
 *
 * 前置：无（纯函数断言，不起浏览器）。
 */
import { expect, test } from "@playwright/test";

import { requiresAttribution } from "../../src/lib/labels";

test.describe("#51 署名规则（前端镜像）", () => {
  for (const [license, expected] of [
    ["CC0 1.0", false],
    ["Public domain", false],
    ["CC BY 4.0", true],
    ["CC BY-SA 4.0", true],
    ["CC BY-NC 4.0", false],
    ["CC BY-ND 4.0", false],
    ["SA 1.0", false],
    ["All rights reserved", false],
    ["", false],
  ] as const) {
    test(`许可「${license || "(空)"}」→ 需署名 ${expected}`, () => {
      expect(requiresAttribution(license)).toBe(expected);
    });
  }
});
