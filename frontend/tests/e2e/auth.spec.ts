/**
 * 账号前端端到端（issue #20 / ADR-0002）。
 *
 * 覆盖验收：未登录守卫重定向、登录/注册/登出、按角色跳转、刷新保持登录态。
 * 依赖后端 seed 账号（teacher@wenjing.local / student@wenjing.local，密码
 * `wenjing123`，可用 WENJING_SEED_PASSWORD 覆盖）。
 *
 * 前置：后端 :8000（已 `make seed`）、前端 :3000。
 */
import { expect, test } from "@playwright/test";

const SEED_PASSWORD = process.env.WENJING_SEED_PASSWORD ?? "wenjing123";
const TEACHER = { email: "teacher@wenjing.local", password: SEED_PASSWORD };

test("未登录访问受保护路由重定向到 /login", async ({ page }) => {
  await page.goto("/teacher");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { name: "登录文境" })).toBeVisible();
});

test("根路径未登录也重定向到 /login", async ({ page }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/login$/);
});

test("教师登录后进入 /teacher，刷新保持登录态，登出后回到 /login", async ({
  page,
}) => {
  await page.goto("/login");
  await page.getByLabel("邮箱或手机号").fill(TEACHER.email);
  await page.getByLabel("密码").fill(TEACHER.password);
  await page.getByRole("button", { name: "登录" }).click();

  await page.waitForURL(/\/teacher$/);
  await expect(page.getByRole("heading", { name: "教师工作台" })).toBeVisible();
  await expect(page.getByText(/演示教师/)).toBeVisible();

  // 刷新：会话 Cookie 仍有效，守卫放行
  await page.reload();
  await expect(page).toHaveURL(/\/teacher$/);
  await expect(page.getByRole("heading", { name: "教师工作台" })).toBeVisible();

  // 登出：回登录页，且再访问受保护路由被拦
  await page.getByRole("button", { name: "登出" }).click();
  await page.waitForURL(/\/login$/);
  await page.goto("/teacher");
  await expect(page).toHaveURL(/\/login$/);
});

test("登录错误按 envelope 展示", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("邮箱或手机号").fill(TEACHER.email);
  await page.getByLabel("密码").fill("wrong-password");
  await page.getByRole("button", { name: "登录" }).click();

  await expect(page.getByText(/AUTH_INVALID_CREDENTIALS/)).toBeVisible();
  await expect(page).toHaveURL(/\/login$/);
});

test("学生注册后进入 /student，且无法进入 /teacher", async ({ page }) => {
  const email = `e2e-${Date.now()}@wenjing.local`;

  await page.goto("/register");
  await page.getByLabel("邮箱").fill(email);
  await page.getByLabel("昵称").fill("E2E 学生");
  await page.getByLabel(/密码/).fill("supersecret1");
  await page.getByRole("button", { name: "注册并登录" }).click();

  await page.waitForURL(/\/student$/);
  await expect(page.getByRole("heading", { name: "学生空间" })).toBeVisible();

  // 学生越权访问教师端 → 重定向回学生首页
  await page.goto("/teacher");
  await expect(page).toHaveURL(/\/student$/);
});
