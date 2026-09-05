/**
 * 共享契约（issue #2）— 前端镜像类型。
 *
 * 单源事实在 backend/app/contracts/（Pydantic）+ contracts/fixtures/*.json。
 * 本文件是其在 TypeScript 侧的手工镜像；协议一致性由以下机制保证：
 * - 契约字段变更时必须同步更新本文件（契约评审 checklist）；
 * - contracts/jsonschema/*.schema.json 由后端导出，供运行时校验（#6 mock server 接入 ajv）；
 * - CI 断言 schema 导出不过期（backend/tests/test_contracts.py）。
 */

export const CONTRACTS_SCHEMA_VERSION = "1.0.0";

// ===== 阶段 / 枚举 =====

export type StageValue =
  | "init"
  | "stage1_creating"
  | "stage1_complete"
  | "stage2_reenacting"
  | "stage2_complete"
  | "stage3_extending"
  | "ended";

export type InteractionMode = "options" | "free_input" | "options_with_fallback";

export type CommandKind =
  | "select_role"
  | "choose_option"
  | "free_input"
  | "rollback_to_event"
  | "enter_stage3"
  | "confirm_ending"
  | "exit_game";

export const ALLOWED_COMMANDS: Record<StageValue, readonly CommandKind[]> = {
  init: [],
  stage1_creating: [],
  stage1_complete: ["select_role", "exit_game"],
  stage2_reenacting: ["choose_option", "free_input", "rollback_to_event", "exit_game"],
  stage2_complete: ["enter_stage3", "exit_game"],
  stage3_extending: [
    "choose_option",
    "free_input",
    "rollback_to_event",
    "confirm_ending",
    "exit_game",
  ],
  ended: [],
};

export type EventType =
  | "session_started"
  | "material_imported"
  | "script_generated"
  | "role_selected"
  | "narrative_advanced"
  | "proposals_generated"
  | "proposals_verified"
  | "interaction_offered"
  | "player_action_recorded"
  | "agent_reactions_done"
  | "stage_transitioned"
  | "rollback_executed";

export type ErrorDomain =
  | "input"
  | "content"
  | "search"
  | "llm"
  | "game"
  | "session"
  | "persistence"
  | "protocol"
  | "internal";

// ===== 材料与证据 =====

export interface MaterialInput {
  schema_version: string;
  source: "paste" | "upload";
  filename: string | null;
  raw_text: string;
}

export interface Material {
  schema_version: string;
  content_hash: string;
  normalized_text: string;
  char_count: number;
  created_at: string | null;
}

/** 按 source_type 判别：original_text | web */
export interface OriginalEvidenceRef {
  source_type: "original_text";
  excerpt: string;
  paragraph_index: number | null;
  char_start: number | null;
  char_end: number | null;
}

export interface WebEvidenceRef {
  source_type: "web";
  url: string;
  title: string;
  fetched_at: string;
  content_hash: string;
  excerpt: string;
}

export type EvidenceRef = OriginalEvidenceRef | WebEvidenceRef;

// ===== 内容管线（issue #9）：体裁判断 + 原文分析 =====

export type GenreType =
  | "novel"
  | "narrative"
  | "drama"
  | "character_story"
  | "expository"
  | "argumentative"
  | "scenery"
  | "poetry"
  | "unknown";

export interface GenreClassification {
  schema_version: string;
  genre: GenreType;
  is_supported: boolean;
  signals: string[];
}

export interface CharacterMention {
  schema_version: string;
  name: string;
  role: string | null;
  personality: string | null;
  evidence_refs: OriginalEvidenceRef[];
}

export interface RelationshipEdge {
  schema_version: string;
  source: string;
  target: string;
  nature: string;
  evidence_refs: OriginalEvidenceRef[];
}

export interface SceneSetting {
  schema_version: string;
  title: string;
  location: string | null;
  participants: string[];
  core_event: string;
  significance: string | null;
  evidence_refs: OriginalEvidenceRef[];
}

export interface KeyEvent {
  schema_version: string;
  title: string;
  description: string;
  participants: string[];
  order: number;
  evidence_refs: OriginalEvidenceRef[];
}

export interface TextAnalysis {
  schema_version: string;
  content_hash: string;
  title: string | null;
  author: string | null;
  genre: GenreClassification;
  characters: CharacterMention[];
  relationships: RelationshipEdge[];
  scenes: SceneSetting[];
  key_events: KeyEvent[];
}


// ===== 剧本包 =====

export interface CharacterProfile {
  name: string;
  public_background: string;
  personality_traits: string[];
  speech_style?: string | null;
  is_player_playable: boolean;
}

export interface Beat {
  beat_id: number;
  description: string;
  is_key_event: boolean;
  evidence_refs: EvidenceRef[];
}

export interface Scene {
  scene_id: number;
  title: string;
  participants: string[];
  beats: Beat[];
}

export interface ScriptPackage {
  schema_version: string;
  title: string;
  characters: CharacterProfile[];
  scenes: Scene[];
  teaching_focus: string[];
  playable_roles: string[];
  stage2_ending_beat_id: number;
}

// ===== 玩家命令 =====

export interface PlayerCommand {
  schema_version: string;
  command_id: string;
  session_id: string;
  kind: CommandKind;
  payload: CommandPayloadByKind[CommandKind];
  issued_at: string | null;
}

export type SelectRolePayload = { role_name: string };
export type ChooseOptionPayload = { option_id: string };
export type FreeInputPayload = { text: string };
export type RollbackToEventPayload = { target_sequence: number };
export type EmptyPayload = Record<string, never>;

export interface CommandPayloadByKind {
  select_role: SelectRolePayload;
  choose_option: ChooseOptionPayload;
  free_input: FreeInputPayload;
  rollback_to_event: RollbackToEventPayload;
  enter_stage3: EmptyPayload;
  confirm_ending: EmptyPayload;
  exit_game: EmptyPayload;
}

// ===== 领域事件 / 运行时状态 =====

export interface DomainEvent {
  schema_version: string;
  event_id: string;
  session_id: string;
  branch_id: string;
  sequence: number;
  event_type: EventType;
  causation_id: string | null;
  correlation_id: string | null;
  payload: Record<string, unknown>;
  occurred_at: string | null;
}

export interface OptionItem {
  option_id: string;
  label: string;
}

export interface ActiveInteraction {
  interaction_id: string;
  mode: InteractionMode;
  prompt: string;
  options: OptionItem[];
  hint: string;
}

export interface Stage3Goal {
  goal_id: number;
  description: string;
  achieved: boolean;
}

export interface RuntimeState {
  schema_version: string;
  session_id: string;
  branch_id: string;
  last_sequence: number;
  stage: StageValue;
  phase: string | null;
  scene_id: number | null;
  beat_cursor: number | null;
  plot_context: Record<string, unknown>;
  character_memories: Record<string, string[]>;
  active_interaction: ActiveInteraction | null;
  stage3_goals: Stage3Goal[];
}

export interface GameSnapshot {
  schema_version: string;
  snapshot_id: string;
  session_id: string;
  branch_id: string;
  last_sequence: number;
  state: RuntimeState;
  created_at: string | null;
}

// ===== 错误 envelope =====

export interface ErrorEnvelope {
  error_id: string;
  code: string;
  domain: ErrorDomain;
  message: string;
  retryable: boolean;
  details: Record<string, unknown> | null;
}

// ===== WebSocket 协议 =====

export interface ServerMessage {
  type:
    | "session_init"
    | "narrative"
    | "character_speech"
    | "system"
    | "interaction"
    | "error";
  session_id: string;
  seq: number;
  payload: ServerMessagePayloads;
}

export interface ContentBlockPayload {
  category: "narrative" | "character_speech" | "system";
  speaker?: string | null;
  text: string;
}

export interface InteractionPayload {
  interaction_id: string;
  mode: InteractionMode;
  prompt: string;
  options: OptionItem[];
  hint: string;
}

export type ServerMessagePayloads =
  | ContentBlockPayload
  | InteractionPayload
  | ErrorEnvelope
  | Record<string, unknown>;

export type ClientMessage =
  | SubmitCommandMessage
  | ConfirmMessagesMessage
  | ResyncRequestMessage;

export interface SubmitCommandMessage {
  type: "submit_command";
  command: PlayerCommand;
}

export interface ConfirmMessagesMessage {
  type: "confirm_messages";
  last_confirmed_seq: number;
}

export interface ResyncRequestMessage {
  type: "resync_request";
  last_confirmed_seq: number;
}
