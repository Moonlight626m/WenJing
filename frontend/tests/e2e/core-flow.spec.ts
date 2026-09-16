/**
 * 学生端核心流程端到端（issue #24，重写自 issue #12 旧核心流程用例）。
 *
 * 覆盖验收：广场浏览与搜索 → 剧本详情 → 开局 → 选角 → 游玩（消息流/交互卡）→
 * 回溯 → 刷新恢复 → 我的游戏续玩；未登录不可见学生空间。
 * 教师先经 UI 建本并发布（fake LLM 模式秒级；真实 LLM 约 100s，故放宽等待）。
 *
 * 前置：后端 :8000（已 `make seed`）、前端 :3000。
 */
import { expect, test } from "@playwright/test";

import { createScript, login, STUDENT, TEACHER } from "./helpers";

test("学生完整核心流程：广场 → 详情 → 开局 → 选角 → 游戏 → 回溯 → 恢复 → 我的游戏", async ({
  page,
}) => {
  test.setTimeout(240_000);
  const name = `E2E 学生流程 ${Date.now()}`;

  // 前置：教师建本并发布（本校可见，学生同 org）
  await login(page, TEACHER);
  await createScript(page, name);
  await expect(page.getByText("生成完成")).toBeVisible({ timeout: 120_000 });
  await page.getByRole("button", { name: "发布", exact: true }).click();
  await expect(page.getByText("已发布").first()).toBeVisible();

  // 切换到学生
  await page.context().clearCookies();
  await login(page, STUDENT);

  // 1. 广场可见且可搜索
  await expect(page.getByRole("heading", { name: "剧本广场" })).toBeVisible();
  await page.getByRole("searchbox").fill(name);
  await expect(page.getByRole("link", { name })).toBeVisible();

  // 2. 详情页
  await page.getByRole("link", { name }).click();
  await page.waitForURL(/\/student\/scripts\/\d+$/);
  await expect(page.getByRole("heading", { name })).toBeVisible();
  await expect(page.getByText("教学重点")).toBeVisible();
  await expect(page.getByRole("button", { name: "开始游玩" })).toBeEnabled();

  // 3. 开局 → 选角
  await page.getByRole("button", { name: "开始游玩" }).click();
  await page.waitForURL(/\/roles\?id=/);
  await expect(page.getByText("选择角色")).toBeVisible();
  // 角色卡从剧本详情重建，含真实简介而非"仅角色名"兜底
  await expect(page.getByText(/是文中人物/).first()).toBeVisible();
  await page.getByRole("button", { name: /扮演此角色/ }).first().click();
  await page.waitForURL(/\/game\?id=/);

  // 4. 游戏页：消息流出现 + 交互卡可选项推进
  const rows = page.getByTestId("message-row");
  await expect(page.getByText("已连接")).toBeVisible();
  await expect(rows.first()).toBeVisible();
  const messagesBefore = await rows.count();
  await expect(page.getByRole("button", { name: /我提议/ }).first()).toBeVisible();
  await page.getByRole("button", { name: /我提议/ }).first().click();
  await expect
    .poll(async () => await rows.count(), { timeout: 30_000 })
    .toBeGreaterThan(messagesBefore);

  // 5. 回溯：选目标 → 回到 → 确认
  await page.locator("select").selectOption({ index: 1 });
  await page.getByRole("button", { name: /回到 #\d+/ }).click();
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(
    page.getByTestId("message-stream").getByText(/已回溯到事件/)
  ).toBeVisible({ timeout: 30_000 });

  // 6. 刷新恢复：session_init 重建 + resync 补发，消息流与连接恢复
  await page.reload();
  await expect(page.getByText("已连接")).toBeVisible({ timeout: 30_000 });
  await expect(rows.first()).toBeVisible();
  await expect(page.locator("header").getByText(/扮演：/)).toBeVisible();

  // 7. 我的游戏：列表有该局并可续玩
  await page.goto("/student");
  const gameRow = page.locator("li", { hasText: name });
  await expect(gameRow).toBeVisible();
  await gameRow.getByRole("button", { name: "继续" }).click();
  await page.waitForURL(/\/game\?id=/);
  await expect(page.getByText("已连接")).toBeVisible({ timeout: 30_000 });
});

test("未登录无法进入学生空间与剧本详情", async ({ page }) => {
  await page.goto("/student");
  await expect(page).toHaveURL(/\/login/);

  await page.goto("/student/scripts/1");
  await expect(page).toHaveURL(/\/login/);
});
