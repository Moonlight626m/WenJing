/**
 * 服务端鉴权助手（issue #20 / ADR-0002 §2）。
 *
 * 受保护路由的 server layout/page 通过 `requireRole` 校验当前会话：读取浏览器
 * 转发的 HttpOnly `wenjing_session` Cookie，向 backend `/api/auth/me` 换取用户与
 * 角色，未登录/越权即重定向。后端仍是最终鉴权方（#18/#19），此处仅做路由守卫。
 *
 * 服务端访问后端地址优先级：
 * - `WENJING_SERVER_API_BASE`（容器内网，如 `http://backend:8000`）
 * - `NEXT_PUBLIC_API_BASE`（本地 dev / CI 的绝对地址）
 * - 由入站请求 `Host` + `X-Forwarded-Proto` 推导（同源生产反代）
 */
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { cache } from "react";

import { apiBaseUrl } from "@/lib/config";
import { roleHome } from "@/lib/role-home";
import type { UserPublic, UserRole } from "@/lib/contracts/types";

const SESSION_COOKIE = "wenjing_session";

/** 各受保护区域允许的角色集合（layout 守卫与 page 复查共用同一来源）。 */
export const TEACHER_ROLES: readonly UserRole[] = ["teacher"];
export const STUDENT_ROLES: readonly UserRole[] = ["student", "teacher"];
export const ADMIN_ROLES: readonly UserRole[] = ["super_admin"];

async function serverApiBase(): Promise<string> {
  const explicit = process.env.WENJING_SERVER_API_BASE;
  if (explicit) return explicit.replace(/\/+$/, "");

  const fromPublic = apiBaseUrl();
  if (fromPublic) return fromPublic;

  const h = await headers();
  const host = h.get("host");
  if (!host) return "";
  const proto = h.get("x-forwarded-proto") ?? "http";
  return `${proto}://${host}`;
}

/** 当前登录用户；`401/403`（未登录/无权限）返回 null。同一渲染 pass 内只请求一次。 */
export const getCurrentUser = cache(async (): Promise<UserPublic | null> => {
  const token = (await cookies()).get(SESSION_COOKIE)?.value;
  if (!token) return null;

  const base = await serverApiBase();
  let resp: Response;
  try {
    resp = await fetch(`${base}/api/auth/me`, {
      headers: { cookie: `${SESSION_COOKIE}=${token}` },
      cache: "no-store",
      signal: AbortSignal.timeout(5000),
    });
  } catch (err) {
    // 后端不可达/超时不是「未登录」：抛出让路由报错，避免把有效会话误判为登出。
    throw new Error(`auth/me unreachable: ${String(err)}`);
  }
  if (resp.status === 401 || resp.status === 403) return null;
  if (!resp.ok) {
    throw new Error(`auth/me failed: HTTP ${resp.status}`);
  }
  return (await resp.json()) as UserPublic;
});

/** 要求已登录；否则重定向 `/login`。 */
export async function requireUser(): Promise<UserPublic> {
  const user = await getCurrentUser();
  if (!user) redirect("/login");
  return user;
}

/** 要求指定角色；未登录 → `/login`，角色不符 → 该用户角色首页。 */
export async function requireRole(
  ...allowed: readonly UserRole[]
): Promise<UserPublic> {
  const user = await requireUser();
  if (!allowed.includes(user.role)) redirect(roleHome(user.role));
  return user;
}
