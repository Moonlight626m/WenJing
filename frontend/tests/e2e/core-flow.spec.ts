/**
 * 核心流程浏览器端到端（issue #12）。
 *
 * 前置：后端运行在 :8000（快速模式 `WENJING_LLM_API_KEY= uv run uvicorn ...`），
 * 前端 dev server 运行在 :3000（`npm run dev`）。
 *
 * 覆盖：创建会话 → 导入课文（粘贴）→ 生成剧本 → 选角 → 游戏页消息流 +
 * 选项推进 → 回溯 → 刷新恢复（session_init 重建 + resync 补发）。
 */
import { expect, test } from "@playwright/test";

const SAMPLE_TEXT =
  "那年冬天，母亲病了。我离开家，到城里去买药。母亲说：路上小心。" +
  "我回头看见她站在门口，眼泪流了下来。我守在母亲的床边，一夜没合眼。" +
  "天亮时，她握住我的手说：去吧。路上雪很大，我走得很慢。";

test("核心流程：创建 → 导入 → 生成 → 选角 → 游戏 → 回溯 → 刷新恢复", async ({
  page,
}) => {
  // 1. 首页创建会话
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "文境" })).toBeVisible();
  await page.getByRole("button", { name: "开始新游戏" }).click();
  await page.waitForURL(/\/import\?id=/);

  // 2. 导入课文（粘贴）
  await page.getByPlaceholder(/粘贴课文原文/).fill(SAMPLE_TEXT);
  await page.getByRole("button", { name: "导入并分析" }).click();
  await expect(page.getByText("原文分析")).toBeVisible();
  await expect(page.getByText(/人物（\d+）/)).toBeVisible();

  // 3. 生成剧本
  await page.getByRole("button", { name: "生成剧本" }).click();
  await expect(page.getByText("剧本已生成。")).toBeVisible();
  await page.getByRole("link", { name: "前去选角" }).first().click();
  await page.waitForURL(/\/roles\?id=/);

  // 4. 选角
  await expect(page.getByText("选择角色")).toBeVisible();
  await page.getByRole("button", { name: /扮演此角色/ }).first().click();
  await page.waitForURL(/\/game\?id=/);

  // 5. 游戏页：消息流出现 + 交互卡可选项推进
  const rows = page.getByTestId("message-row");
  await expect(page.getByText("已连接")).toBeVisible();
  await expect(rows.first()).toBeVisible();
  const messagesBefore = await rows.count();
  await expect(page.getByRole("button", { name: /我提议/ }).first()).toBeVisible();
  await page.getByRole("button", { name: /我提议/ }).first().click();
  await expect
    .poll(async () => await rows.count(), { timeout: 30_000 })
    .toBeGreaterThan(messagesBefore);

  // 6. 回溯：选目标 → 回到 → 确认
  await page.locator("select").selectOption({ index: 1 });
  await page.getByRole("button", { name: /回到 #\d+/ }).click();
  await page.getByRole("button", { name: "确认", exact: true }).click();
  await expect(
    page.getByTestId("message-stream").getByText(/已回溯到事件/)
  ).toBeVisible({ timeout: 30_000 });

  // 7. 刷新恢复：session_init 重建 + resync 补发，消息流与连接恢复
  await page.reload();
  await expect(page.getByText("已连接")).toBeVisible({ timeout: 30_000 });
  await expect(rows.first()).toBeVisible();
  await expect(page.locator("header").getByText(/扮演：/)).toBeVisible();
});
