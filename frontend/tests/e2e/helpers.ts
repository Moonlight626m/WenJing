/** E2E 共用 helper：seed 账号登录与教师建本（登录带 hydration 竞态重试）。 */
import { expect, type Page } from "@playwright/test";

const SEED_PASSWORD = process.env.WENJING_SEED_PASSWORD ?? "123456";
export const ADMIN = { email: "admin", password: SEED_PASSWORD };
export const TEACHER = { email: "teacher", password: SEED_PASSWORD };
export const STUDENT = { email: "student", password: SEED_PASSWORD };

export const SAMPLE_TEXT =
  "那年冬天，母亲病了。我离开家，到城里去买药。母亲说：路上小心。" +
  "我回头看见她站在门口，眼泪流了下来。我守在母亲的床边，一夜没合眼。" +
  "天亮时，她握住我的手说：去吧。路上雪很大，我走得很慢。";

export async function login(page: Page, account: typeof TEACHER) {
  // 客户端组件未完成 hydration 时点击会触发原生表单 GET（URL 带查询参数）：
  // 等网络空闲，并在万一发生时重试整次登录。
  for (let attempt = 0; attempt < 3; attempt++) {
    await page.goto("/login");
    await page.waitForLoadState("networkidle");
    await page.getByLabel("邮箱或手机号").fill(account.email);
    await page.getByLabel("密码").fill(account.password);
    await page.getByRole("button", { name: "登录" }).click();
    try {
      await page.waitForURL(/\/(admin|teacher|student)$/, { timeout: 5000 });
      return;
    } catch {
      // 重新加载 /login 再试一次
    }
  }
  throw new Error("登录失败：多次尝试未进入角色首页");
}

/** 新建剧本：导入素材 → 命名 → 创建并生成（等待跳转详情页，不校验生成完成）。 */
export async function createScript(page: Page, name: string) {
  await page.goto("/teacher/new");
  await page.waitForLoadState("networkidle");
  await page.getByPlaceholder(/粘贴课文原文/).fill(SAMPLE_TEXT);
  await page.getByRole("button", { name: "导入并分析" }).click();
  await expect(page.getByText(/素材已导入/)).toBeVisible();

  await page.getByLabel("剧本名称").fill(name);
  await page.getByRole("button", { name: "创建并生成" }).click();
  await page.waitForURL(/\/teacher\/scripts\/\d+$/);
}
