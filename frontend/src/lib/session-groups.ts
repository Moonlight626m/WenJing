import type { SessionSummary } from "@/lib/contracts/types";

/** 同一剧本下的所有剧情世界：「我的游戏」以剧本为一行，点进去才展开各局。 */
export interface ScriptGameGroup {
  scriptId: number;
  /** 剧本名（剧本被删后后端 outerjoin 为 null）。 */
  scriptName: string | null;
  /** 按最近游玩倒序。 */
  sessions: SessionSummary[];
}

/**
 * 会话时间戳（毫秒）。缺失或非法按 0 处理：降序排序时沉底，
 * 升序（如按开局先后编号）时会排在最前。
 */
export function sessionTimeMs(value: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

/** 按最近游玩倒序（组内/组间/剧情世界列表共用同一口径）。 */
export function sortSessionsByRecent(
  sessions: SessionSummary[]
): SessionSummary[] {
  return [...sessions].sort(
    (a, b) => sessionTimeMs(b.updated_at) - sessionTimeMs(a.updated_at)
  );
}

/** 「第 N 局」编号：按开局先后（created_at 升序），与展示顺序解耦。 */
export function numberSessionsByStart(
  sessions: SessionSummary[]
): Map<string, number> {
  const ordered = [...sessions].sort(
    (a, b) =>
      sessionTimeMs(a.created_at) - sessionTimeMs(b.created_at) ||
      sessionTimeMs(a.updated_at) - sessionTimeMs(b.updated_at)
  );
  return new Map(
    ordered.map((session, index) => [session.session_id, index + 1])
  );
}

/**
 * 按剧本聚合剧情世界，组内与组间都按最近更新倒序。
 *
 * 同一个剧本可以被反复开局（每次 `open_session` 都是新会话），平铺列表会把
 * 同一篇课文铺成 N 行，看不出「这是一部戏的第几局」。没有 `script_id` 的旧会话
 * 无法归档，单独返回由调用方按单局渲染。
 */
export function groupSessionsByScript(sessions: SessionSummary[]): {
  groups: ScriptGameGroup[];
  ungrouped: SessionSummary[];
} {
  const byScript = new Map<number, SessionSummary[]>();
  const ungrouped: SessionSummary[] = [];
  for (const session of sessions) {
    if (session.script_id == null) {
      ungrouped.push(session);
      continue;
    }
    const bucket = byScript.get(session.script_id);
    if (bucket) bucket.push(session);
    else byScript.set(session.script_id, [session]);
  }
  const groups = [...byScript.entries()]
    .map(([scriptId, items]) => {
      const ordered = sortSessionsByRecent(items);
      return { scriptId, scriptName: ordered[0].script_name, sessions: ordered };
    })
    .sort(
      (a, b) =>
        sessionTimeMs(b.sessions[0].updated_at) -
        sessionTimeMs(a.sessions[0].updated_at)
    );
  return { groups, ungrouped };
}
