/**
 * 教师端剧本库端到端（issue #23 / ADR-0002 §3）。
 *
 * 覆盖验收：导入 → 生成 → 预览 → 发布全流程、可见性切换与下架、删除草稿、
 * 生成进度可见、非教师不可进入。
 * 依赖后端 seed 账号（teacher@wenjing.local / student@wenjing.local，密码
 * `wenjing123`，可用 WENJING_SEED_PASSWORD 覆盖）。
 *
 * 生成走 STAGE1：确定性 fake 模式（未配置 WENJING_LLM_API_KEY）秒级完成；
 * 真实 LLM 模式约 100s，故放宽等待。
 *
 * 前置：后端 :8000（已 `make seed`）、前端 :3000。
 */
import { expect, test } from "@playwright/test";

import { createScript, login, STUDENT, TEACHER } from "./helpers";

test("教师完成导入 → 生成 → 预览 → 发布 → 可见性切换 → 下架", async ({
  page,
}) => {
  test.setTimeout(180_000);
  const name = `E2E 剧本 ${Date.now()}`;
  await login(page, TEACHER);
  await createScript(page, name);

  // 生成进度 → 完成 → 预览可见
  await expect(page.getByText("生成完成")).toBeVisible({ timeout: 120_000 });
  await expect(page.getByText("教学重点")).toBeVisible();
  await expect(page.getByText(/可扮演角色/)).toBeVisible();

  // 发布（默认本校可见）
  await page.getByRole("button", { name: "发布", exact: true }).click();
  await expect(page.getByText("已发布").first()).toBeVisible();

  // 可见性切换为公开（刷新后从服务端读回，确认已持久化）
  await page.locator("select").selectOption("public");
  await page.getByRole("button", { name: "更新可见性" }).click();
  await page.reload();
  await expect(page.locator("select")).toHaveValue("public");

  // 下架 → 重新发布
  page.on("dialog", (dialog) => void dialog.accept());
  await page.getByRole("button", { name: "下架" }).click();
  await expect(page.getByText("已下架").first()).toBeVisible();
  await page.getByRole("button", { name: "重新发布" }).click();
  await expect(page.getByText("已发布").first()).toBeVisible();

  // 剧本库按状态归档
  await page.goto("/teacher");
  await expect(page.getByRole("heading", { name: /已发布（\d+）/ })).toBeVisible();
  await expect(page.getByText(name)).toBeVisible();
});

test("教师可删除草稿", async ({ page }) => {
  test.setTimeout(180_000);
  const name = `E2E 待删剧本 ${Date.now()}`;
  page.on("dialog", (dialog) => void dialog.accept());

  await login(page, TEACHER);
  await createScript(page, name);
  await expect(page.getByText("生成完成")).toBeVisible({ timeout: 120_000 });

  await page.getByRole("button", { name: "删除草稿" }).click();
  await page.waitForURL(/\/teacher$/);
  await expect(page.getByText(name)).toHaveCount(0);
});

test("学生无法进入教师端创作页", async ({ page }) => {
  await login(page, STUDENT);

  await page.goto("/teacher/new");
  await expect(page).toHaveURL(/\/student$/);

  await page.goto("/teacher/scripts/1");
  await expect(page).toHaveURL(/\/student$/);
});
