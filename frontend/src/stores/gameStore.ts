"use client";

import { create } from "zustand";

import type {
  ActiveInteraction,
  AssetRef,
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
  /** 会话内单调递增的确认水位；**瞬态消息没有它**（见 `LiveStream`）。 */
  seq?: number;
  session_id?: string;
  payload: Record<string, unknown>;
}

/**
 * 流式字幕的**瞬态**缓冲（#60/#61）：只有 `stream_id`，没有 `seq`，也不进消息流。
 *
 * 它描述的是"此刻屏幕上滚动的字幕"，权威文本永远是随后那条 `character_speech`
 * ——终态规则：收到它即丢弃对应角色的缓冲（见 `settleStreams`）。`ended` 标记
 * `stream_end` 已到但持久发言尚未到，此时该行退回普通字幕的停留/淡出节奏，
 * 万一持久发言永远不来（角色反应失败）也不会留一条永不消失的字幕。
 */
export interface LiveStream {
  streamId: string;
  speaker: string;
  text: string;
  ended: boolean;
}

/**
 * `stream_*` 消息 → 新的流缓冲；与本条无关时返回 null（调用方保持原引用）。
 *
 * 纯函数，便于不起浏览器直接断言（`tests/e2e/streaming.spec.ts`）。
 */
export function applyStreamMessage(
  streams: LiveStream[],
  message: WireMessage
): LiveStream[] | null {
  const payload = (message.payload ?? {}) as Record<string, unknown>;
  const streamId = typeof payload.stream_id === "string" ? payload.stream_id : "";
  if (!streamId) return null;
  const index = streams.findIndex((item) => item.streamId === streamId);

  if (message.type === "stream_start") {
    if (index >= 0) return null; // 重复的 start（重发/串线）不重置已有文本
    return [
      ...streams,
      {
        streamId,
        speaker: typeof payload.speaker === "string" ? payload.speaker : "角色",
        text: "",
        ended: false,
      },
    ];
  }
  if (index < 0) return null; // 没见过的 stream_id：start 没到就来的增量一律丢弃

  if (message.type === "stream_delta") {
    const text = typeof payload.text === "string" ? payload.text : "";
    if (!text) return null;
    return streams.map((item, i) =>
      i === index ? { ...item, text: item.text + text } : item
    );
  }
  if (message.type === "stream_end") {
    return streams.map((item, i) => (i === index ? { ...item, ended: true } : item));
  }
  return null;
}

/** 终态规则（ADR-0005 §10）：该角色的持久发言到达 → 丢弃它的流缓冲。 */
export function settleStreams(
  streams: LiveStream[],
  speaker: string | null
): LiveStream[] {
  if (streams.length === 0) return streams;
  return streams.filter((item) => item.speaker !== speaker);
}

type Sender = (message: unknown) => void;

/** 命令发出后无响应的等待窗口；超时用同一 command_id 重发（服务端幂等对账）。 */
export const RESEND_DELAY_MS = 120_000;

/**
 * 运行期配图就绪（#56）的应用规则：返回应写入的状态，或 null 表示这条要丢掉。
 *
 * 丢掉两种情形：**场景已过期**（配图在玩家走开之后才到，换上会闪回上一幕的背景）
 * 与载荷缺字段。纯函数，便于不起浏览器直接断言（`tests/e2e/asset-ready.spec.ts`）。
 */
export function applyAssetReady(
  state: { sceneKey: string | null; currentAsset: AssetRef | null },
  payload: Record<string, unknown>
): { currentAsset: AssetRef } | null {
  const sceneKey = typeof payload.scene_key === "string" ? payload.scene_key : null;
  const asset = payload.current_asset;
  if (!sceneKey || sceneKey !== state.sceneKey) return null;
  if (asset == null || typeof asset !== "object") return null;
  return { currentAsset: asset as AssetRef };
}

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
  /** 当前场景稳定键（#53）：背景切换/淡入的判定来源。 */
  sceneKey: string | null;
  /** 当前场景标题（#53）：随 plot_advancement 更新。 */
  sceneTitle: string | null;
  /** 当前背景稳定引用（#53）：页面据此经鉴权端点换预签名 URL。 */
  currentAsset: AssetRef | null;
  selectedRole: string | null;
  messages: ChatMessage[];
  /** 在途的流式字幕（#61）：只有 stream_id，没有 seq，不入消息流。 */
  streams: LiveStream[];
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
    sceneKey: null,
    sceneTitle: null,
    currentAsset: null,
    selectedRole: null,
    messages: [],
    streams: [],
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
        streams: [],
        interaction: null,
        allowedCommands: [],
        pending: null,
        connection: "connecting",
        sceneKey: null,
        sceneTitle: null,
        currentAsset: null,
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

      // 瞬态流式字幕（#60/#61）：没有 seq，不进消息流、不推进确认水位、不结算
      // pending——它只影响"此刻屏幕上的字幕"。
      if (msg.type.startsWith("stream_")) {
        const next = applyStreamMessage(get().streams, msg);
        if (next) set({ streams: next });
        return;
      }

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
          // 场景背景（#53）：权威快照携带，重连即恢复当前背景与场景标题
          // 重连的权威快照：在途流属于**上一条连接**，一并丢弃（字幕的收束
          // 由随后的 character_speech 事件负责，不靠流缓冲）
          streams: [],
          sceneKey:
            typeof payload.scene_key === "string" ? payload.scene_key : null,
          sceneTitle:
            typeof payload.scene_title === "string" ? payload.scene_title : null,
          currentAsset:
            payload.current_asset != null &&
            typeof payload.current_asset === "object"
              ? (payload.current_asset as AssetRef)
              : null,
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

      if (msg.type === "asset_ready") {
        // 命令外事件（#56）：不是命令响应，故不 markCommandSettled，也不进消息流。
        // 确认水位仍由 chat 消息的 maxSeq 推进——把配图的 seq 也算进去会在它与
        // 命令消息乱序到达时把尚未收到的叙事消息一并确认掉。
        const next = applyAssetReady(get(), payload);
        if (next) set(next);
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
      let sceneKey = state.sceneKey;
      let sceneTitle = state.sceneTitle;
      let currentAsset = state.currentAsset;
      let streams = state.streams;

      // 终局批次可能多条消息共享同一 seq（如"进入阶段：ended"+"已结束"），
      // 去重键需包含文本，否则第二条会被误判重复
      const text0 = typeof payload.text === "string" ? payload.text : "";
      const key =
        msg.type === "interaction"
          ? `${seq}:interaction`
          : `${seq}:${msg.type}:${text0}`;
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
        const speaker =
          typeof payload.speaker === "string" ? payload.speaker : null;
        messages = [
          ...messages,
          { key, seq, kind: msg.type as ChatKind, text, speaker },
        ];
        // 终态规则：这条持久发言就是该角色流缓冲的归宿，接收即丢弃缓冲，
        // 屏幕上不会同时留下"滚动中的"与"最终的"两份文本
        if (msg.type === "character_speech") {
          streams = settleStreams(streams, speaker);
        }
        if (msg.type === "narrative") {
          // 场景切换（#53）：narrative 消息携带 scene_key/scene_title/current_asset，
          // GameStage 按 sceneKey 变化触发淡入、按 currentAsset 换背景
          const nextSceneKey =
            typeof payload.scene_key === "string" ? payload.scene_key : null;
          if (nextSceneKey) {
            sceneKey = nextSceneKey;
            sceneTitle =
              typeof payload.scene_title === "string" ? payload.scene_title : null;
            if (payload.current_asset != null && typeof payload.current_asset === "object") {
              currentAsset = payload.current_asset as AssetRef;
            } else {
              currentAsset = null; // 该场景无图 → 降级为渐变
            }
          }
        }
        if (msg.type === "system") {
          const stageMatch = /进入阶段：(\S+)/.exec(text);
          if (stageMatch) stage = asStage(stageMatch[1]);
          if (text.includes("已结束")) {
            interaction = null;
            allowedCommands = [];
          }
        }
      }

      set({
        messages,
        streams,
        interaction,
        allowedCommands,
        stage,
        sceneKey,
        sceneTitle,
        currentAsset,
      });

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
