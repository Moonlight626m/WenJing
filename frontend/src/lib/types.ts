export type MessageType =
  | "narrative"
  | "character_speech"
  | "interaction"
  | "system"
  | "phase_transition"
  | "player_action"
  | "rollback_request"
  | "system_command";

export interface BaseMessage {
  type: MessageType;
  id?: number;
  session_id?: string;
  content: Record<string, unknown>;
  timestamp: number;
}

export interface NarrativeMessage extends BaseMessage {
  type: "narrative";
}

export interface CharacterSpeechMessage extends BaseMessage {
  type: "character_speech";
}

export interface InteractionMessage extends BaseMessage {
  type: "interaction";
}

export interface SystemMessage extends BaseMessage {
  type: "system";
}

export interface PhaseTransitionMessage extends BaseMessage {
  type: "phase_transition";
}

export type ServerMessage =
  | NarrativeMessage
  | CharacterSpeechMessage
  | InteractionMessage
  | SystemMessage
  | PhaseTransitionMessage;

export type InteractionMode = "options" | "free_input" | "options_with_fallback";

export interface GameStageInfo {
  stage: string;
  phase: string | null;
  event_count: number;
  latest_event_id: number;
}
