import type { Connection } from "@/stores/gameStore";

/** 空舞台的三态：等待 WS / 已连上但权威快照仍在补算 / 已就绪。 */
export type SceneStatus = "connecting" | "restoring" | "ready";

/**
 * 连接状态 + `session_init` 是否到达 → 空舞台该显示什么。
 *
 * WS `connected` 不代表能玩：Stage3 的 `session_init` 会先补算离线 tick
 * （最多 3 轮 LLM），期间没有消息、也不能拿旧交互点继续提交。断线时权威快照
 * 失效，重连拿不到 `session_init` 之前都按未就绪处理。
 */
export function sceneStatus(
  connection: Connection,
  sessionInitialized: boolean
): SceneStatus {
  if (!sessionInitialized) {
    return connection === "connected" ? "restoring" : "connecting";
  }
  return connection === "connected" ? "ready" : "connecting";
}

export function sceneStatusText(status: SceneStatus): string {
  switch (status) {
    case "connecting":
      return "正在连接…";
    case "restoring":
      return "正在重建世界…";
    case "ready":
      return "等待剧情开始…";
  }
}
