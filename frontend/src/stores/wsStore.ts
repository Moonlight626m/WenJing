import { create } from "zustand";

import type { ServerMessage } from "@/lib/types";

type ConnectionStatus = "connecting" | "open" | "closed" | "error";

interface WsState {
  status: ConnectionStatus;
  lastMessage: ServerMessage | null;
  reconnectAttempts: number;
  setStatus: (status: ConnectionStatus) => void;
  setLastMessage: (message: ServerMessage) => void;
  reset: () => void;
}

export const useWsStore = create<WsState>((set) => ({
  status: "connecting",
  lastMessage: null,
  reconnectAttempts: 0,
  setStatus: (status) => set({ status }),
  setLastMessage: (message) => set({ lastMessage: message }),
  reset: () => set({ status: "connecting", lastMessage: null, reconnectAttempts: 0 }),
}));
