import type { GameStageInfo } from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!resp.ok) {
    throw new Error(`API error ${resp.status}: ${await resp.text()}`);
  }
  return resp.json() as Promise<T>;
}

export function createSession(): Promise<{ session_id: string; stage: string }> {
  return request("/api/sessions", { method: "POST" });
}

export function getSession(id: string): Promise<GameStageInfo> {
  return request(`/api/sessions/${id}`);
}
