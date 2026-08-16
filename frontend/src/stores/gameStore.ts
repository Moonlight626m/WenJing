import { create } from "zustand";

import type { ServerMessage } from "@/lib/types";

interface GameState {
  sessionId: string | null;
  stage: string;
  messages: ServerMessage[];
  latestEventId: number;
  setSession: (sessionId: string, stage: string) => void;
  addMessage: (message: ServerMessage) => void;
  setStage: (stage: string) => void;
}

export const useGameStore = create<GameState>((set) => ({
  sessionId: null,
  stage: "init",
  messages: [],
  latestEventId: 0,
  setSession: (sessionId, stage) =>
    set({ sessionId, stage, messages: [], latestEventId: 0 }),
  addMessage: (message) =>
    set((state) => ({
      messages: [...state.messages, message],
      latestEventId: message.id ?? state.latestEventId,
    })),
  setStage: (stage) => set({ stage }),
}));
