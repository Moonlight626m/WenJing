import { create } from "zustand";

interface UiState {
  sidebarOpen: boolean;
  rollbackActive: boolean;
  rollbackTarget: number | null;
  toggleSidebar: () => void;
  setRollback: (active: boolean, target?: number | null) => void;
}

export const useUiStore = create<UiState>((set) => ({
  sidebarOpen: true,
  rollbackActive: false,
  rollbackTarget: null,
  toggleSidebar: () => set((state) => ({ sidebarOpen: !state.sidebarOpen })),
  setRollback: (active, target = null) =>
    set({ rollbackActive: active, rollbackTarget: target }),
}));
