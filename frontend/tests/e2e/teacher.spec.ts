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
import type { Page } from "@playwright/test";

const SEED_PASSWORD = process.env.WENJING_SEED_PASSWORD ?? "wenjing123";
const TEACHER = { email: "teacher@wenjing.local", password: SEED_PASSWORD };
const STUDENT = { email: "student@wenjing.local", password: SEED_PASSWORD };

const SAMPLE_TEXT =
  "那年冬天，母亲病了。我离开家，到城里去买药。母亲说：路上小心。" +
  "我回头看见她站在门口，眼泪流了下来。我守在母亲的床边，一夜没合眼。" +
  "天亮时，她握住我的手说：去吧。路上雪很大，我走得很慢。";

async function login(page: Page, account: typeof TEACHER) {
  // 客户端组件未完成 hydration 时点击会触发原生表单 GET（URL 带查询参数）：
  // 等网络空闲，并在万一发生时重试整次登录。
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await page.getByLabel("邮箱或手机号").fill(account.email);
    await page.getByLabel("密码").fill(account.password);
    await page.getByRole("button", { name: "登录" }).click();
    try {
      await page.waitForURL(/\/(teacher|student)$/, { timeout: 5000 });
      return;
    } catch {
      // 重新加载 /login 再试一次
    }
  }
  throw new Error("登录失败：多次尝试未进入角色首页");
}

/** 新建剧本：导入素材 → 命名 → 创建并生成，返回剧本名。 */
async function createScript(page: Page, name: string) {
  await page.goto("/teacher/new");
  await page.waitForLoadState("networkidle");
  await page.getByPlaceholder(/粘贴课文原文/).fill(SAMPLE_TEXT);
  await page.getByRole("button", { name: "导入并分析" }).click();
  await expect(page.getByText(/素材已导入/)).toBeVisible();

  await page.getByLabel("剧本名称").fill(name);
  await page.getByRole("button", { name: "创建并生成" }).click();
  await page.waitForURL(/\/teacher\/scripts\/\d+$/);
}

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
