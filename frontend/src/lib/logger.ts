/**
 * 轻量分级日志（admin / teacher / student 三端共用）：
 * - [info]  常规接口信息（请求、响应）
 * - [warning] 业务错误（4xx envelope，页面可恢复展示）
 * - [error] 系统错误（网络失败、未知错误）
 *
 * 仅打 console；可用 NEXT_PUBLIC_LOG_LEVEL 过滤（debug < info < warning < error）。
 */

const LEVELS = { debug: 10, info: 20, warning: 30, error: 40 } as const;

type LevelName = keyof typeof LEVELS;

const minLevel: number =
  LEVELS[
    (process.env.NEXT_PUBLIC_LOG_LEVEL as LevelName | undefined) ?? "info"
  ] ?? LEVELS.info;

function enabled(level: LevelName): boolean {
  return LEVELS[level] >= minLevel;
}

export const logger = {
  debug(...args: unknown[]) {
    if (enabled("debug")) console.debug("[debug]", ...args);
  },
  info(...args: unknown[]) {
    if (enabled("info")) console.info("[info]", ...args);
  },
  warning(...args: unknown[]) {
    if (enabled("warning")) console.warn("[warning]", ...args);
  },
  error(...args: unknown[]) {
    if (enabled("error")) console.error("[error]", ...args);
  },
};
