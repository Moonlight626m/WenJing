"use client";

import { create } from "zustand";

import type {
  ActiveInteraction,
  CharacterProfile,
  CommandKind,
  CommandPayloadByKind,
  PlayerCommand,
  ScriptPackage,
  StageValue,
} from "@/lib/contracts/types";
import { buildCommand } from "@/lib/session-cache";
import { useUiStore } from "@/stores/uiStore";

export type Connection =
  | "idle"
  | "connecting"
  | "connected"
  | "reconnecting"
  | "closed";

export type ChatKind = "narrative" | "character_speech" | "system";

export interface ChatMessage {
  key: string;
  seq: number;
  kind: ChatKind;
  text: string;
  speaker: string | null;
}

export interface PendingCommand {
  commandId: string;
  kind: CommandKind;
  label: string;
  sentAt: number;
  retries: number;
  command: PlayerCommand;
}

export interface WireMessage {
  type: string;
  seq: number;
  session_id?: string;
  payload: Record<string, unknown>;
}

type Sender = (message: unknown) => void;

/** 命令发出后无响应的等待窗口；超时用同一 command_id 重发（服务端幂等对账）。 */
export const RESEND_DELAY_MS = 120_000;

const STAGES: StageValue[] = [
  "init",
  "stage1_creating",
  "stage1_complete",
  "stage2_reenacting",
  "stage2_complete",
  "stage3_extending",
  "ended",
];

function asStage(value: string): StageValue {
  return STAGES.includes(value as StageValue) ? (value as StageValue) : "init";
}

function maxSeq(messages: ChatMessage[]): number {
  return messages.reduce((acc, m) => Math.max(acc, m.seq), 0);
}

interface GameStore {
  sessionId: string | null;
  stage: StageValue;
  branchId: string | null;
  playerRole: string | null;
  plotLog: string[];
  scriptTitle: string | null;
  playableRoles: string[];
  characters: CharacterProfile[];
  selectedRole: string | null;
  messages: ChatMessage[];
  interaction: ActiveInteraction | null;
  allowedCommands: CommandKind[];
  pending: PendingCommand | null;
  connection: Connection;
  sender: Sender | null;

  resetSession: (sessionId: string) => void;
  setConnection: (connection: Connection) => void;
  setSender: (sender: Sender) => void;
  setScriptInfo: (pkg: ScriptPackage) => void;
  setStatusInfo: (status: {
    stage: string;
    playable_roles: string[];
    selected_role: string | null;
  }) => void;
  handleServerMessage: (message: unknown) => void;
  submitCommand: <K extends CommandKind>(
    kind: K,
    payload: CommandPayloadByKind[K],
    label?: string
  ) => void;
}

export const useGameStore = create<GameStore>((set, get) => {
  let resendTimer: ReturnType<typeof setTimeout> | null = null;

  function clearResendTimer() {
    if (resendTimer !== null) {
      clearTimeout(resendTimer);
      resendTimer = null;
    }
  }

  function scheduleResend() {
    clearResendTimer();
    const current = get().pending;
    if (!current) return;
    const remaining = Math.max(0, RESEND_DELAY_MS - (Date.now() - current.sentAt));
    resendTimer = setTimeout(() => {
      const pending = get().pending;
      if (!pending || pending.commandId !== current.commandId) return;
      if (pending.retries >= 1) {
        clearResendTimer();
        set({ pending: null });
        useUiStore.getState().push({
          kind: "error",
          title: `命令未响应：${pending.label}`,
          description: "已用同一命令 ID 重试一次仍未收到响应，请刷新页面恢复会话",
        });
        return;
      }
      const sender = get().sender;
      if (!sender) return;
      sender({ type: "submit_command", command: pending.command });
      set({
        pending: { ...pending, retries: pending.retries + 1, sentAt: Date.now() },
      });
      scheduleResend();
    }, remaining);
  }

  function markCommandSettled() {
    clearResendTimer();
    if (get().pending) set({ pending: null });
  }

  return {
    sessionId: null,
    stage: "init",
    branchId: null,
    playerRole: null,
    plotLog: [],
    scriptTitle: null,
    playableRoles: [],
    characters: [],
    selectedRole: null,
    messages: [],
    interaction: null,
    allowedCommands: [],
    pending: null,
    connection: "idle",
    sender: null,

    resetSession: (sessionId) => {
      clearResendTimer();
      set({
        sessionId,
        stage: "init",
        branchId: null,
        playerRole: null,
        plotLog: [],
        messages: [],
        interaction: null,
        allowedCommands: [],
        pending: null,
        connection: "connecting",
      });
    },

    setConnection: (connection) => set({ connection }),

    setSender: (sender) => set({ sender }),

    setScriptInfo: (pkg) =>
      set({
        scriptTitle: pkg.title,
        playableRoles: pkg.playable_roles,
        characters: pkg.characters,
      }),

    setStatusInfo: (status) =>
      set((state) => ({
        stage: asStage(status.stage),
        playableRoles: status.playable_roles.length
          ? status.playable_roles
          : state.playableRoles,
        selectedRole: status.selected_role ?? state.playerRole,
        playerRole: status.selected_role ?? state.playerRole,
      })),

    handleServerMessage: (raw) => {
      if (typeof raw !== "object" || raw === null) return;
      const msg = raw as WireMessage;
      const seq = typeof msg.seq === "number" ? msg.seq : 0;
      const payload = (msg.payload ?? {}) as Record<string, unknown>;

      if (msg.type === "error") {
        markCommandSettled();
        useUiStore.getState().push({
          kind: "error",
          title: typeof payload.code === "string" ? payload.code : "错误",
          description:
            typeof payload.message === "string" ? payload.message : "未知错误",
        });
        return;
      }

      if (msg.type === "session_init") {
        const ix = (payload.active_interaction as ActiveInteraction | null) ?? null;
        set({
          stage: asStage(String(payload.stage ?? "init")),
          branchId: typeof payload.branch_id === "string" ? payload.branch_id : null,
          playerRole:
            typeof payload.player_role === "string" ? payload.player_role : null,
          plotLog: Array.isArray(payload.plot_log)
            ? payload.plot_log.map(String)
            : [],
          interaction: ix,
          allowedCommands: (Array.isArray(payload.allowed_commands)
            ? payload.allowed_commands
            : []) as CommandKind[],
        });
        // 权威重建后按本地确认水位请求补发（首连为 0 → 服务端从 DB 全量重建）。
        // session_init 本身不计入确认水位（服务端补发协议排除引导消息）。
        get()
          .sender?.({
            type: "resync_request",
            last_confirmed_seq: maxSeq(get().messages),
          });
        return;
      }

      if (
        msg.type !== "narrative" &&
        msg.type !== "character_speech" &&
        msg.type !== "system" &&
        msg.type !== "interaction"
      ) {
        return;
      }

      // 命令已产生响应：清除 pending 并停止重发
      markCommandSettled();

      const state = get();
      let messages = state.messages;
      let interaction = state.interaction;
      let allowedCommands = state.allowedCommands;
      let stage = state.stage;

      const key = `${seq}:${msg.type}`;
      if (msg.type === "interaction") {
        // 交互点不进消息流（交互卡单独渲染），但会刷新当前交互与允许命令
        const ix = (payload.interaction as ActiveInteraction | null) ?? null;
        if (ix) {
          interaction = ix;
          allowedCommands = ((payload.allowed_commands as string[]) ??
            []) as CommandKind[];
        }
      } else if (!messages.some((m) => m.key === key)) {
        const text = typeof payload.text === "string" ? payload.text : "";
        messages = [
          ...messages,
          {
            key,
            seq,
            kind: msg.type as ChatKind,
            text,
            speaker: typeof payload.speaker === "string" ? payload.speaker : null,
          },
        ];
        if (msg.type === "system") {
          const stageMatch = /进入阶段：(\S+)/.exec(text);
          if (stageMatch) stage = asStage(stageMatch[1]);
          if (text.includes("已结束")) {
            interaction = null;
            allowedCommands = [];
          }
        }
      }

      set({ messages, interaction, allowedCommands, stage });

      // 确认水位推进：通知服务端修剪本连接 outbox
      get()
        .sender?.({
          type: "confirm_messages",
          last_confirmed_seq: maxSeq(messages),
        });
    },

    submitCommand: (kind, payload, label) => {
      const { sessionId, sender, pending, allowedCommands } = get();
      if (!sessionId || !sender || pending) return; // 单飞行：等待当前命令响应
      if (!allowedCommands.includes(kind)) return;
      const command = buildCommand(sessionId, kind, payload);
      sender({ type: "submit_command", command });
      set({
        pending: {
          commandId: command.command_id,
          kind,
          label: label ?? kind,
          sentAt: Date.now(),
          retries: 0,
          command,
        },
      });
      scheduleResend();
    },
  };
});
