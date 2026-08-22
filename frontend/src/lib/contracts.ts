/**
 * Shared Contracts —— 前端镜像（与 backend/app/contracts 一一对应）。
 *
 * 同步规则（contracts/README.md）：
 * - 枚举值与后端 ``StrEnum`` 字符串完全一致；
 * - 结构仅含可序列化字段（不被 WebSocket/FastAPI/ORM 污染）；
 * - breaking change 需两名模块 owner review，并同时更新 fixtures。
 *
 * 类型的形状由 ``frontend/src/lib/contracts/fixtures.ts`` 通过 typed imports
 * 绑定到权威 JSON fixtures，``tsc --noEmit`` 即 fixture ↔ TS 同步断言。
 */

// ===== 枚举（值对齐后端 StrEnum）=====

export const GameStage = {
  INIT: "init",
  STAGE1_CREATING: "stage1_creating",
  STAGE1_COMPLETE: "stage1_complete",
  STAGE2_REENACTING: "stage2_reenacting",
  STAGE2_COMPLETE: "stage2_complete",
  STAGE3_EXTENDING: "stage3_extending",
  ENDED: "ended",
} as const;
export type GameStage = (typeof GameStage)[keyof typeof GameStage];

export const InteractionPhase = {
  NARRATIVE: "narrative",
  DIRECTION: "direction",
  AGENT_PROPOSAL: "agent_proposal",
  VERIFICATION: "verification",
  INTERACTION_DESIGN: "interaction_design",
  PLAYER_TURN: "player_turn",
  AGENT_REACTION: "agent_reaction",
  STAGE_CHECK: "stage_check",
} as const;
export type InteractionPhase = (typeof InteractionPhase)[keyof typeof InteractionPhase];

export const InteractionMode = {
  OPTIONS: "options",
  FREE_INPUT: "free_input",
  OPTIONS_WITH_FALLBACK: "options_with_fallback",
} as const;
export type InteractionMode = (typeof InteractionMode)[keyof typeof InteractionMode];

export const RuntimeStatus = {
  RUNNING: "running",
  WAITING_PLAYER: "waiting_player",
  STAGE_COMPLETE: "stage_complete",
  ENDED: "ended",
} as const;
export type RuntimeStatus = (typeof RuntimeStatus)[keyof typeof RuntimeStatus];

export const CommandType = {
  CHOOSE_OPTION: "choose_option",
  FREE_INPUT: "free_input",
  ROLLBACK: "rollback",
  CONFIRM_STAGE2_ENDING: "confirm_stage2_ending",
  DECLINE_STAGE3: "decline_stage3",
  END_GAME: "end_game",
} as const;
export type CommandType = (typeof CommandType)[keyof typeof CommandType];

export const CommandStatus = {
  PENDING: "pending",
  COMMITTED: "committed",
  REJECTED: "rejected",
  FAILED: "failed",
} as const;
export type CommandStatus = (typeof CommandStatus)[keyof typeof CommandStatus];

export const GenreKind = {
  NOVEL: "novel",
  NARRATIVE_PROSE: "narrative_prose",
  DRAMA: "drama",
  CHARACTER_STORY: "character_story",
  UNKNOWN: "unknown",
} as const;
export type GenreKind = (typeof GenreKind)[keyof typeof GenreKind];

export const EventType = {
  STAGE_TRANSITIONED: "stage_transitioned",
  SCRIPT_LOADED: "script_loaded",
  INTERACTION_PRESENTED: "interaction_presented",
  PLAYER_ACTED: "player_acted",
  NARRATIVE_ADVANCED: "narrative_advanced",
  CHARACTER_SPOKE: "character_spoke",
  ROLLBACK_EXECUTED: "rollback_executed",
  BRANCH_CREATED: "branch_created",
  STAGE3_GOAL_UPDATED: "stage3_goal_updated",
  GAME_ENDED: "game_ended",
} as const;
export type EventType = (typeof EventType)[keyof typeof EventType];

// ===== 材料与证据 =====

export interface MaterialInput {
  raw_text: string;
  source_type: "paste" | "file";
  filename: string | null;
  schema_version: number;
}

export interface Material {
  material_id: string;
  session_id: string;
  raw_text: string;
  content_hash: string;
  genre: GenreKind;
  encoding: "utf-8";
  filename: string | null;
  created_at: string;
  schema_version: number;
}

export interface OriginalEvidenceRef {
  source_type: "original";
  excerpt: string;
  paragraph_id: number | null;
  char_start: number | null;
  char_end: number | null;
  schema_version: number;
}

export interface WebEvidenceRef {
  source_type: "web";
  url: string;
  title: string;
  retrieved_at: string;
  content_hash: string;
  excerpt: string;
  schema_version: number;
}

export type EvidenceRef = OriginalEvidenceRef | WebEvidenceRef;

// ===== 剧本 =====

export interface CharacterSetting {
  name: string;
  role: string;
  description: string;
  personality: string;
  background: string;
  is_player_playable: boolean;
}

export interface Beat {
  beat_id: number;
  title: string;
  description: string;
}

export interface Scene {
  scene_id: number;
  title: string;
  setting: string;
  beats: Beat[];
}

export interface Stage2Beat extends Beat {
  character_ids: string[];
  evidence: OriginalEvidenceRef[];
}

export interface ScriptPackage {
  script_id: string;
  title: string;
  genre: GenreKind;
  characters: CharacterSetting[];
  scenes: Scene[];
  stage2_beats: Stage2Beat[];
  teaching_focus: string[];
  player_playable_roles: string[];
  stage2_ending_beat_id: number;
  stage3_resume: string;
  schema_version: number;
}

// ===== 命令 / 事件 =====

export interface PlayerCommand {
  command_id: string;
  session_id: string;
  type: CommandType;
  payload: Record<string, unknown>;
  issued_at: string;
  schema_version: number;
}

export interface DomainEvent {
  event_id: number;
  session_id: string;
  branch_id: string;
  sequence: number;
  type: EventType;
  causation_id: string | null;
  correlation_id: string;
  timestamp: string;
  payload: Record<string, unknown>;
  schema_version: number;
}

// ===== 运行时 =====

export interface InteractionPoint {
  mode: InteractionMode;
  prompt: string;
  options: string[];
  hint: string;
  character_name: string | null;
}

export interface CharacterState {
  name: string;
  is_player: boolean;
  memory: string[];
  meta: Record<string, unknown>;
}

export interface RuntimeState {
  session_id: string;
  stage: GameStage;
  phase: InteractionPhase | null;
  active_branch_id: string;
  head_event_id: number;
  event_count: number;
  beat_index: number;
  total_beats: number;
  stage2_ending_confirmed: boolean;
  stage3_goal: string | null;
  stage3_round_taken: number;
  player_role: string | null;
  characters: CharacterState[];
  plot_context: string[];
  schema_version: number;
}

export interface GameSnapshot {
  snapshot_id: string;
  session_id: string;
  branch_id: string;
  event_id: number;
  state: RuntimeState;
  created_at: string;
  schema_version: number;
}

export interface RuntimeUpdate {
  state: RuntimeState;
  events: DomainEvent[];
  interaction: InteractionPoint | null;
  allowed_commands: CommandType[];
  status: RuntimeStatus;
  schema_version: number;
}

// ===== 错误 =====

export const ErrorCode = {
  INPUT_INVALID: "INPUT_INVALID",
  INPUT_EMPTY: "INPUT_EMPTY",
  INPUT_TOO_LARGE: "INPUT_TOO_LARGE",
  INPUT_UNSUPPORTED_ENCODING: "INPUT_UNSUPPORTED_ENCODING",
  INPUT_UNSUPPORTED_EXTENSION: "INPUT_UNSUPPORTED_EXTENSION",
  CONTENT_UNSUPPORTED_GENRE: "CONTENT_UNSUPPORTED_GENRE",
  CONTENT_ANALYSIS_FAILED: "CONTENT_ANALYSIS_FAILED",
  SEARCH_FAILED: "SEARCH_FAILED",
  SEARCH_FETCH_FAILED: "SEARCH_FETCH_FAILED",
  LLM_CALL_FAILED: "LLM_CALL_FAILED",
  LLM_TIMEOUT: "LLM_TIMEOUT",
  LLM_OUTPUT_INVALID: "LLM_OUTPUT_INVALID",
  GAME_INVALID_COMMAND: "GAME_INVALID_COMMAND",
  GAME_INVALID_STAGE: "GAME_INVALID_STAGE",
  GAME_ALREADY_ENDED: "GAME_ALREADY_ENDED",
  SESSION_NOT_FOUND: "SESSION_NOT_FOUND",
  SESSION_CONFLICT: "SESSION_CONFLICT",
  PERSISTENCE_FAILED: "PERSISTENCE_FAILED",
  PERSISTENCE_CONFLICT: "PERSISTENCE_CONFLICT",
  PROTOCOL_INVALID_MESSAGE: "PROTOCOL_INVALID_MESSAGE",
  INTERNAL_ERROR: "INTERNAL_ERROR",
  INTERNAL_UNHANDLED: "INTERNAL_UNHANDLED",
} as const;
export type ErrorCode = (typeof ErrorCode)[keyof typeof ErrorCode];

export interface ErrorEnvelope {
  error_id: string;
  code: ErrorCode;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
  schema_version: number;
}

// ===== REST DTO =====

export type SessionStatus = "created" | "material_ready" | "script_ready" | "playing" | "ended";

export interface SessionView {
  session_id: string;
  created_at: string;
  status: SessionStatus;
  stage: GameStage;
  schema_version: number;
}

export interface MaterialView {
  material_id: string;
  session_id: string;
  content_hash: string;
  genre: GenreKind;
  filename: string | null;
  char_count: number;
  created_at: string;
  schema_version: number;
}

export type GenerationStep = "classifying" | "researching" | "generating" | "validating";

export interface GenerationProgress {
  step: GenerationStep;
  step_label: string;
  progress: number;
  message: string;
}

export interface ScriptView {
  script: ScriptPackage;
  summary: string;
  schema_version: number;
}

export interface GenerationView {
  status: "running" | "complete" | "failed";
  progress: GenerationProgress | null;
  script: ScriptView | null;
  error: ErrorEnvelope | null;
  schema_version: number;
}

export interface RuntimeView {
  session_id: string;
  stage: GameStage;
  phase: InteractionPhase | null;
  interaction: InteractionPoint | null;
  allowed_commands: CommandType[];
  status: RuntimeStatus;
  event_count: number;
  head_event_id: number;
  character_names: string[];
  player_role: string | null;
  stage2_ending_confirmed: boolean;
  stage3_goal: string | null;
  schema_version: number;
}

// ===== WebSocket OutboundMessage =====

export const MessageType = {
  SESSION_INIT: "session_init",
  MATERIAL_READY: "material_ready",
  GENERATION_PROGRESS: "generation_progress",
  GENERATION_COMPLETE: "generation_complete",
  GENERATION_FAILED: "generation_failed",
  RUNTIME_UPDATE: "runtime_update",
  SESSION_ERROR: "session_error",
  SESSION_ENDED: "session_ended",
} as const;
export type MessageType = (typeof MessageType)[keyof typeof MessageType];

interface OutboundBase {
  message_id: string;
  session_id: string;
  correlation_id: string | null;
  in_response_to_command_id: string | null;
  sequence: number | null;
  sent_at: string;
  schema_version: number;
}

export interface SessionInitPayload {
  stage: GameStage;
  phase: InteractionPhase | null;
  last_acked_sequence: number | null;
  runtime: RuntimeView | null;
}

export interface SessionEndedPayload {
  reason: "ended" | "declined_stage3" | "error";
  summary: string;
}

export interface SessionInitMessage extends OutboundBase {
  type: "session_init";
  payload: SessionInitPayload;
}

export interface MaterialReadyMessage extends OutboundBase {
  type: "material_ready";
  payload: MaterialView;
}

export interface GenerationProgressMessage extends OutboundBase {
  type: "generation_progress";
  payload: GenerationProgress;
}

export interface GenerationCompleteMessage extends OutboundBase {
  type: "generation_complete";
  payload: ScriptView;
}

export interface GenerationFailedMessage extends OutboundBase {
  type: "generation_failed";
  payload: ErrorEnvelope;
}

export interface RuntimeUpdateMessage extends OutboundBase {
  type: "runtime_update";
  payload: RuntimeView;
}

export interface SessionErrorMessage extends OutboundBase {
  type: "session_error";
  payload: ErrorEnvelope;
}

export interface SessionEndedMessage extends OutboundBase {
  type: "session_ended";
  payload: SessionEndedPayload;
}

export type OutboundMessage =
  | SessionInitMessage
  | MaterialReadyMessage
  | GenerationProgressMessage
  | GenerationCompleteMessage
  | GenerationFailedMessage
  | RuntimeUpdateMessage
  | SessionErrorMessage
  | SessionEndedMessage;