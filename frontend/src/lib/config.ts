/**
 * 运行时/构建期端点配置。
 *
 * 优先级：
 * - REST：`NEXT_PUBLIC_API_BASE`（显式设置，空串表示同源相对路径）
 *   → 未设置时回落到本地 dev 后端 `http://localhost:8000`。
 * - WS：`NEXT_PUBLIC_WS_BASE`（显式设置）→ 由 REST base 推导（http→ws）
 *   → 浏览器同源（反代部署）。
 *
 * 生产部署推荐由反向代理统一域名：设置 `NEXT_PUBLIC_API_BASE=`（空），
 * 前端即以同源 `/api`、`/ws` 访问，无需知道后端端口。
 */

const RAW_API_BASE = process.env.NEXT_PUBLIC_API_BASE;
const RAW_WS_BASE = process.env.NEXT_PUBLIC_WS_BASE;

function stripTrailingSlash(value: string): string {
  return value.replace(/\/+$/, "");
}

export function apiBaseUrl(): string {
  if (RAW_API_BASE === undefined) return "http://localhost:8000";
  return stripTrailingSlash(RAW_API_BASE);
}

export function wsBaseUrl(): string {
  if (RAW_WS_BASE !== undefined && RAW_WS_BASE !== "") {
    return stripTrailingSlash(RAW_WS_BASE);
  }
  const apiBase = apiBaseUrl();
  if (apiBase) return apiBase.replace(/^http/, "ws");
  if (typeof window !== "undefined") {
    const proto = window.location.protocol === "https:" ? "wss" : "ws";
    return `${proto}://${window.location.host}`;
  }
  return "ws://localhost:8000";
}
