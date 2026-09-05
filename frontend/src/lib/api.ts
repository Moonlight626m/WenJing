import type {
  ErrorEnvelope,
  MaterialInput,
  ScriptPackage,
  TextAnalysis,
} from "@/lib/contracts/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  readonly envelope: ErrorEnvelope;
  readonly status: number;

  constructor(envelope: ErrorEnvelope, status: number) {
    super(envelope.message);
    this.name = "ApiError";
    this.envelope = envelope;
    this.status = status;
  }
}

function isEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return typeof v.code === "string" && typeof v.message === "string";
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let resp: Response;
  try {
    resp = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(
      {
        error_id: "network",
        code: "NETWORK_UNREACHABLE",
        domain: "internal",
        message: "无法连接服务端，请确认后端已启动",
        retryable: true,
        details: null,
      },
      0
    );
  }
  if (!resp.ok) {
    const body = await resp.text();
    let parsed: unknown = null;
    try {
      parsed = JSON.parse(body);
    } catch {
      // 非 JSON 错误体（如代理层错误页）
    }
    if (isEnvelope(parsed)) {
      throw new ApiError(parsed, resp.status);
    }
    throw new ApiError(
      {
        error_id: "unknown",
        code: "INTERNAL_ERROR",
        domain: "internal",
        message: body.slice(0, 200) || `HTTP ${resp.status}`,
        retryable: false,
        details: null,
      },
      resp.status
    );
  }
  return resp.json() as Promise<T>;
}

// ===== REST DTO（backend/app/contracts/dto.py 镜像）=====

export interface SessionStatus {
  session_id: string;
  stage: string;
  active_branch_id: string;
  head_sequence: number;
  playable_roles: string[];
  selected_role: string | null;
  generation: GenerationProgress | null;
}

export interface GenerationProgress {
  status: "idle" | "running" | "succeeded" | "failed";
  phases: { name: string; state: string; detail: string | null }[];
}

export interface RuntimeUpdateDto {
  session_id: string;
  branch_id: string;
  state: import("@/lib/contracts/types").RuntimeState;
  new_events: { event_id: string; sequence: number; event_type: string }[];
  terminal: boolean;
  emitted_event_types: string[];
}

// ===== 端点 =====

export function createSession(): Promise<{ session_id: string }> {
  return request("/api/sessions", { method: "POST" });
}

export function getStatus(sessionId: string): Promise<SessionStatus> {
  return request(`/api/sessions/${sessionId}`);
}

export function importMaterial(
  sessionId: string,
  input: MaterialInput
): Promise<TextAnalysis> {
  return request(`/api/sessions/${sessionId}/material`, {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function generateScript(sessionId: string): Promise<ScriptPackage> {
  return request(`/api/sessions/${sessionId}/generate`, { method: "POST" });
}

export function submitCommandRest(
  sessionId: string,
  command: import("@/lib/contracts/types").PlayerCommand
): Promise<RuntimeUpdateDto> {
  return request(`/api/sessions/${sessionId}/commands`, {
    method: "POST",
    body: JSON.stringify(command),
  });
}
