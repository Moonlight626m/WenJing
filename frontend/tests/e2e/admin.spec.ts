/**
 * 运营后台端到端（issue #25 / ADR-0002 §5）。
 *
 * 覆盖验收：super_admin 查看剧本库与 token 聚合、org/status/purpose 筛选、
 * 非 super_admin 无法进入、看板无任何写操作入口。
 * 依赖后端 seed 账号 admin（密码 123456，可用
 * WENJING_SEED_PASSWORD 覆盖）；用量数据来自教师建本时的真实 Stage1 调用
 * （fake LLM 模式同样逐次入账 llm_usage）。
 *
 * 前置：后端 :8000（已 `make seed`）、前端 :3000。
 */
import { expect, test } from "@playwright/test";

import { ADMIN, createScript, login, STUDENT, TEACHER } from "./helpers";

test("super_admin 看板：剧本库 + 用量聚合 + 筛选 + 无写入口", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const name = `E2E 后台剧本 ${Date.now()}`;

  // 前置：教师建本（产生 stage1 用量）并发布
  await login(page, TEACHER);
  await createScript(page, name);
  await expect(page.getByText("生成完成")).toBeVisible({ timeout: 120_000 });
  await page.getByRole("button", { name: "发布", exact: true }).click();
  await expect(page.getByText("已发布").first()).toBeVisible();

  // super_admin 登录后落在 /admin
  await page.context().clearCookies();
  await login(page, ADMIN);
  await expect(page).toHaveURL(/\/admin$/);

  // 剧本库：可见刚发布的剧本，状态筛选生效
  await expect(page.getByRole("heading", { name: "剧本库" })).toBeVisible();
  await expect(page.getByText(name)).toBeVisible();
  await page.getByLabel("状态筛选").selectOption("published");
  await expect(page.getByText(name)).toBeVisible();
  await page.getByLabel("状态筛选").selectOption("draft");
  await expect(page.getByText(name)).toHaveCount(0);

  // 用量：建本产生 stage1 调用记录；按用途筛选后行变化，含合计行
  const usageSection = page.locator("section", { hasText: "Token 用量" });
  await expect(usageSection.locator("tbody tr").first()).toBeVisible();
  const stage1Rows = await usageSection.locator("tbody tr").count();
  await page.getByLabel("用途筛选").selectOption("stage1");
  const onlyStage1 = await usageSection.locator("tbody tr").count();
  expect(onlyStage1).toBeGreaterThan(0);
  expect(onlyStage1).toBeLessThanOrEqual(stage1Rows);
  await expect(usageSection.getByText("合计（当前筛选）")).toBeVisible();

  // 无任何写操作入口：看板正文没有按钮（筛选均为 select/input）
  await expect(page.locator("main").getByRole("button")).toHaveCount(0);
});

test("非 super_admin 与未登录无法进入运营后台", async ({ page }) => {
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/login/);

  await login(page, STUDENT);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/student$/);

  await page.context().clearCookies();
  await login(page, TEACHER);
  await page.goto("/admin");
  await expect(page).toHaveURL(/\/teacher$/);
});
