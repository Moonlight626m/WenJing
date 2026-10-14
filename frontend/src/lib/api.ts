import { apiBaseUrl } from "@/lib/config";
import { logger } from "@/lib/logger";
import type {
  AssetRef,
  AssetUrlResponse,
  AuthSessionInfo,
  ErrorEnvelope,
  GenerationResumeRequest,
  GenerationProgress,
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
  TranscribeResponse,
  UsageAggregateResponse,
} from "@/lib/contracts/types";
import { CONTRACTS_SCHEMA_VERSION } from "@/lib/contracts/types";

const MUTATING_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);

/**
 * 游戏命令的客户端等待上限（毫秒）。
 *
 * 命令是**同步长任务**：选角那一条要等后端跑完 N 个角色提议 + 若干轮验证（真实
 * LLM，并发受 `WENJING_MAX_CONCURRENT_LLM` 限制）才返回，前端拿到响应才跳转。
 * 单次 LLM 调用的预算本身是 `WENJING_LLM_TIMEOUT_SECONDS`（缺省 240s），故这里取
 * 同量级：正常生成远快于此，撞到它说明是真的卡住了——宁可报错也不要无限转圈。
 */
const COMMAND_TIMEOUT_MS = 240_000;

/** 生成尝试的终态：SSE 收到即收流（后端同款三元组的镜像，见 services/progress_hub.py）。 */
const FINAL_GENERATION_STATUSES = new Set([
  "succeeded",
  "failed",
  "awaiting_review",
]);

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

/** `request()` 的可选开关。 */
interface RequestOptions {
  /**
   * 请求超时（毫秒）。缺省**不设**——只有已知的同步长任务才该设（见
   * `COMMAND_TIMEOUT_MS`），其余端点保持原有行为。
   *
   * 超时只解除客户端的等待，服务端会把命令跑完并落库；因此超时后重试必须复用
   * 同一个 `command_id`，否则幂等闸认不出是同一条命令（见 `roles` 页的复用）。
   */
  timeoutMs?: number;
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options?: RequestOptions
): Promise<T> {
  const method = (init?.method ?? "GET").toUpperCase();
  const isFormData = init?.body instanceof FormData;
  const headers: Record<string, string> = {
    // FormData 由浏览器自设 Content-Type（含 multipart boundary），不能覆盖
    ...(isFormData ? {} : { "Content-Type": "application/json" }),
    ...(init?.headers as Record<string, string> | undefined),
  };
  if (MUTATING_METHODS.has(method)) {
    const csrf = readCsrfToken();
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  const timeoutMs = options?.timeoutMs;
  const controller = timeoutMs ? new AbortController() : null;
  const timer =
    controller && timeoutMs ? setTimeout(() => controller.abort(), timeoutMs) : null;

  let resp: Response;
  try {
    resp = await fetch(`${apiBaseUrl()}${path}`, {
      ...init,
      credentials: "include",
      headers,
      ...(controller ? { signal: controller.signal } : {}),
    });
  } catch (err) {
    if (controller?.signal.aborted) {
      logger.error(`请求超时 ${method} ${path}（${timeoutMs}ms）`);
      throw new ApiError(
        {
          error_id: "timeout",
          code: "REQUEST_TIMEOUT",
          domain: "internal",
          message: `等待超过 ${Math.round((timeoutMs ?? 0) / 1000)} 秒仍未响应；服务端可能仍在生成，可稍后重试或直接继续游玩`,
          retryable: true,
          details: null,
        },
        0
      );
    }
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
  } finally {
    if (timer !== null) clearTimeout(timer);
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
  // #33 退役遗留：旧「已生成完才有值」的占位形状，无人消费；新代码用
  // contracts 的 GenerationProgress（lib/contracts/types）
  generation: import("@/lib/contracts/types").GenerationProgress | null;
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
    body: JSON.stringify({ schema_version: CONTRACTS_SCHEMA_VERSION, script_id: scriptId }),
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
  // 命令是唯一游戏输入入口，也是唯一同步长任务端点（首轮要跑完所有角色的提议与
  // 验证），故只有它带超时；见 COMMAND_TIMEOUT_MS。
  return request(
    `/api/sessions/${sessionId}/commands`,
    {
      method: "POST",
      body: JSON.stringify(command),
    },
    { timeoutMs: COMMAND_TIMEOUT_MS }
  );
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
    body: JSON.stringify({ schema_version: CONTRACTS_SCHEMA_VERSION, ...input }),
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

/** 教师闸门恢复（#34）：审阅后从断点继续，指令/编辑/终审动作注入 workflow。 */
export function resumeScriptGeneration(
  scriptId: number,
  payload: Omit<GenerationResumeRequest, "schema_version">
): Promise<ScriptDetail> {
  return request(`/api/scripts/${scriptId}/generation/resume`, {
    method: "POST",
    body: JSON.stringify({
      schema_version: CONTRACTS_SCHEMA_VERSION,
      ...payload,
    } satisfies GenerationResumeRequest),
  });
}

export function regenerateScript(scriptId: number): Promise<ScriptDetail> {
  return request(`/api/scripts/${scriptId}/regenerate`, { method: "POST" });
}

/** 教师停止运行中的生成：取消进程内任务并回写失败终态（含教师可读原因）。 */
export function cancelScriptGeneration(scriptId: number): Promise<ScriptDetail> {
  return request(`/api/scripts/${scriptId}/generation/cancel`, {
    method: "POST",
  });
}

/**
 * 订阅生成进度 SSE 流（教师详情页实时增强，权威终态仍在 GET 详情）。
 *
 * 返回关闭函数；收到终态帧（succeeded/failed/awaiting_review）后流会由
 * 服务端收束，onSnapshot 不再触发。网络/鉴权错误经 onError 上报后由
 * 调用方决定回落轮询还是静默。
 */
export function subscribeGenerationProgress(
  scriptId: number,
  onSnapshot: (snapshot: GenerationProgress) => void,
  onDone?: () => void
): () => void {
  // 原生 EventSource 而非 request() 统一通道：SSE 是流式只读响应，不存在
  // JSON envelope/CSRF 语义（GET 无需 CSRF）；错误语义为「断线自动重连」。
  const source = new EventSource(
    `${apiBaseUrl()}/api/scripts/${scriptId}/generation/stream`,
    { withCredentials: true }
  );
  let done = false;
  const finishOnce = () => {
    if (done) return;
    done = true;
    onDone?.();
  };
  source.onmessage = (event) => {
    try {
      const parsed = JSON.parse(event.data) as GenerationProgress;
      onSnapshot(parsed);
      if (FINAL_GENERATION_STATUSES.has(parsed.status)) {
        source.close();
        finishOnce();
      }
    } catch (err) {
      logger.warning("generation SSE 帧解析失败", err);
    }
  };
  source.onerror = () => {
    // 浏览器会自动重连；终态后的收束由服务端保证，这里只记日志
    logger.info("generation SSE 断开（浏览器自动重连）");
  };
  return () => {
    source.close();
    finishOnce();
  };
}

export function publishScript(
  scriptId: number,
  visibility: ScriptPublishRequest["visibility"]
): Promise<ScriptSummary> {
  return request(`/api/scripts/${scriptId}/publish`, {
    method: "POST",
    body: JSON.stringify({ schema_version: CONTRACTS_SCHEMA_VERSION, visibility }),
  });
}

export function unpublishScript(scriptId: number): Promise<ScriptSummary> {
  return request(`/api/scripts/${scriptId}/unpublish`, { method: "POST" });
}

export function deleteScript(scriptId: number): Promise<void> {
  return request(`/api/scripts/${scriptId}`, { method: "DELETE" });
}

// ===== 资产（#49/#50，backend/app/controllers/assets.py 镜像）=====

/** 预签名 URL 物化（短时效）：教师审阅面板按 asset_id 换取可显示的图片地址。 */
export function fetchAssetUrl(assetId: string): Promise<AssetUrlResponse> {
  return request(`/api/assets/${assetId}/url`);
}

/** 教师自有素材上传（#49）：multipart；成功返回 READY 的稳定引用。 */
export function uploadScriptAsset(
  scriptId: number,
  input: { subjectKey: string; kind: "background" | "avatar" | "fullbody"; file: File }
): Promise<AssetRef> {
  const form = new FormData();
  form.set("subject_key", input.subjectKey);
  form.set("kind", input.kind);
  form.set("image", input.file);
  return request(`/api/scripts/${scriptId}/assets/upload`, {
    method: "POST",
    body: form,
  });
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
    body: JSON.stringify({ schema_version: CONTRACTS_SCHEMA_VERSION, ...input }),
  });
}

export function login(input: Omit<LoginRequest, "schema_version">): Promise<AuthSessionInfo> {
  return request("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ schema_version: CONTRACTS_SCHEMA_VERSION, ...input }),
  });
}

export function logout(): Promise<void> {
  return request("/api/auth/logout", { method: "POST" });
}

// ===== 语音输入（#64）=====

/**
 * 上传一段录音换取文本。
 *
 * **只上传、不落库**：服务端在请求内用完即弃，不回传音频也不写事件流。拿到
 * `text` 后由调用方当普通 `free_input` 命令提交——命令端点仍是唯一游戏输入入口。
 */
export function transcribeSpeech(
  sessionId: string,
  audio: Blob,
  durationMs: number
): Promise<TranscribeResponse> {
  const form = new FormData();
  // 文件名按容器给：有些 provider 按扩展名判格式（后端也会兜一层白名单）
  form.append("audio", audio, "speech.webm");
  form.append("duration_ms", String(Math.max(0, Math.round(durationMs))));
  return request(`/api/sessions/${sessionId}/transcribe`, {
    method: "POST",
    body: form,
  });
}
