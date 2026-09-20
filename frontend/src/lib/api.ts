import { apiBaseUrl } from "@/lib/config";
import { logger } from "@/lib/logger";
import type {
  AuthSessionInfo,
  ErrorEnvelope,
  LoginRequest,
  MaterialInput,
  MaterialPublic,
  RegisterRequest,
  ScriptCreateRequest,
  ScriptDetail,
  ScriptListResponse,
  ScriptPublishRequest,
  ScriptSummary,
  SessionListResponse,
  UsageAggregateResponse,
} from "@/lib/contracts/types";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

function readCsrfToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)wenjing_csrf=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

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

/** 统一把错误渲染为 `code：message`（envelope）或原始字符串。 */
export function formatApiError(err: unknown): string {
  if (err instanceof ApiError) {
    return `${err.envelope.code}：${err.envelope.message}`;
  }
  return String(err);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (MUTATING_METHODS.has(method)) {
    const csrf = readCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  let resp: Response;
  try {
    resp = await fetch(`${apiBaseUrl()}${path}`, {
      ...init,
      credentials: "include",
      headers,
    });
  } catch (err) {
    logger.error(`请求失败（网络） ${method} ${path}`, err);
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
      // 业务错误（4xx envelope）：warning，页面可恢复展示
      logger.warning(`响应 ${resp.status} ${method} ${path}`, parsed);
      throw new ApiError(parsed, resp.status);
    }
    const envelope = {
      error_id: "unknown",
      code: "INTERNAL_ERROR",
      domain: "internal",
      message: body.slice(0, 200) || `HTTP ${resp.status}`,
      retryable: false,
      details: null,
    } satisfies ErrorEnvelope;
    logger.error(`响应 ${resp.status}（非 envelope） ${method} ${path}`, envelope);
    throw new ApiError(envelope, resp.status);
  }
  logger.info(`请求 ${method} ${path} → ${resp.status}`);
  if (resp.status === 204) {
    return undefined as T;
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

/** 学生从剧本开局：POST /api/sessions {script_id} → 201 SessionStatusResponse。 */
export function openSession(scriptId: number): Promise<SessionStatus> {
  return request("/api/sessions", {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0.0", script_id: scriptId }),
  });
}

export function getStatus(sessionId: string): Promise<SessionStatus> {
  return request(`/api/sessions/${sessionId}`);
}

/** 我的游戏列表（GET /api/sessions，仅自己的剧情世界）。 */
export function listMySessions(): Promise<SessionListResponse> {
  return request("/api/sessions");
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

// ===== 剧本库（教师创作，backend/app/api/scripts.py 镜像）=====

/** 剧本广场：org + public 的已发布剧本（backend GET /api/scripts/square）。 */
export function listSquareScripts(): Promise<ScriptListResponse> {
  return request("/api/scripts/square");
}

export function listMyScripts(): Promise<ScriptListResponse> {
  return request("/api/scripts");
}

export function importSourceMaterial(
  input: MaterialInput
): Promise<MaterialPublic> {
  return request("/api/materials", {
    method: "POST",
    body: JSON.stringify(input),
  });
}

export function createScriptDraft(
  input: Omit<ScriptCreateRequest, "schema_version">
): Promise<ScriptSummary> {
  return request("/api/scripts", {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0.0", ...input }),
  });
}

export function getScriptDetail(scriptId: number): Promise<ScriptDetail> {
  return request(`/api/scripts/${scriptId}`);
}

export function startScriptGeneration(
  scriptId: number
): Promise<ScriptDetail> {
  return request(`/api/scripts/${scriptId}/generate`, { method: "POST" });
}

export function regenerateScript(scriptId: number): Promise<ScriptDetail> {
  return request(`/api/scripts/${scriptId}/regenerate`, { method: "POST" });
}

export function publishScript(
  scriptId: number,
  visibility: ScriptPublishRequest["visibility"]
): Promise<ScriptSummary> {
  return request(`/api/scripts/${scriptId}/publish`, {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0.0", visibility }),
  });
}

export function unpublishScript(scriptId: number): Promise<ScriptSummary> {
  return request(`/api/scripts/${scriptId}/unpublish`, { method: "POST" });
}

export function deleteScript(scriptId: number): Promise<void> {
  return request(`/api/scripts/${scriptId}`, { method: "DELETE" });
}

// ===== 运营后台（super_admin 只读，backend/app/api/admin.py 镜像）=====

function toQuery(params: Record<string, string | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value) search.set(key, value);
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export function listAdminScripts(
  filters: { orgId?: string | null; status?: string | null } = {}
): Promise<ScriptListResponse> {
  return request(
    `/api/admin/scripts${toQuery({ org_id: filters.orgId, status: filters.status })}`
  );
}

export function listAdminUsage(
  filters: {
    orgId?: string | null;
    purpose?: string | null;
    since?: string | null;
    until?: string | null;
  } = {}
): Promise<UsageAggregateResponse> {
  return request(
    `/api/admin/usage${toQuery({
      org_id: filters.orgId,
      purpose: filters.purpose,
      since: filters.since,
      until: filters.until,
    })}`
  );
}

// ===== 账号（backend/app/api/auth.py 镜像）=====

export function register(input: Omit<RegisterRequest, "schema_version">): Promise<AuthSessionInfo> {
  return request("/api/auth/register", {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0.0", ...input }),
  });
}

export function login(input: Omit<LoginRequest, "schema_version">): Promise<AuthSessionInfo> {
  return request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ schema_version: "1.0.0", ...input }),
  });
}

export function logout(): Promise<void> {
  return request("/api/auth/logout", { method: "POST" });
}
