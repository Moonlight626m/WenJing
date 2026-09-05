import type {
  PlayerCommand,
  CommandKind,
  CommandPayloadByKind,
} from "@/lib/contracts/types";

const STORAGE_KEY = "wenjing.sessions";
const MAX_RECORDS = 10;

export interface SessionRecord {
  sessionId: string;
  stage: string;
  title: string | null;
  playerRole: string | null;
  updatedAt: string;
}

export function loadRecents(): SessionRecord[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed) ? (parsed as SessionRecord[]) : [];
  } catch {
    return [];
  }
}

// ===== useSyncExternalStore 适配（首页最近会话列表）=====

const listeners = new Set<() => void>();
let snapshotCache: SessionRecord[] | null = null;
const EMPTY: SessionRecord[] = [];

function notify() {
  snapshotCache = null;
  for (const listener of listeners) listener();
}

export function subscribeRecents(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function getRecentsSnapshot(): SessionRecord[] {
  if (snapshotCache === null) snapshotCache = loadRecents();
  return snapshotCache;
}

export function getServerRecentsSnapshot(): SessionRecord[] {
  return EMPTY;
}

export function upsertRecent(record: SessionRecord): void {
  if (typeof window === "undefined") return;
  const rest = loadRecents().filter((r) => r.sessionId !== record.sessionId);
  const next = [record, ...rest].slice(0, MAX_RECORDS);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  notify();
}

export function removeRecent(sessionId: string): void {
  if (typeof window === "undefined") return;
  const next = loadRecents().filter((r) => r.sessionId !== sessionId);
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  notify();
}

export function buildCommand<K extends CommandKind>(
  sessionId: string,
  kind: K,
  payload: CommandPayloadByKind[K]
): PlayerCommand {
  return {
    schema_version: "1.0.0",
    command_id: crypto.randomUUID(),
    session_id: sessionId,
    kind,
    payload,
    issued_at: new Date().toISOString(),
  };
}

/** 按阶段决定恢复会话时应进入的页面（id 作为 query 参数拼接）。 */
export function routeForStage(
  sessionId: string,
  stage: string,
  selectedRole: string | null
): string {
  const q = `?id=${sessionId}`;
  if (stage === "init" || stage === "stage1_creating") return `/import${q}`;
  if (stage === "stage1_complete") return selectedRole ? `/game${q}` : `/roles${q}`;
  return `/game${q}`;
}
