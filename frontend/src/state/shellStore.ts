import { create } from "zustand";

import type { BackendConnectionState, BootstrapResponse } from "../api/client";

export type RouteId =
  | "assistant"
  | "teaching"
  | "skills"
  | "compositions"
  | "brain"
  | "brain-specialists"
  | "settings";

export interface ShellState {
  activeRoute: RouteId;
  backend: BackendConnectionState | null;
  userDisplayName: string;
  userStatusLabel: string;
  navigation: BootstrapResponse["navigation"];
  setRoute: (route: RouteId) => void;
  hydrate: (bootstrap: BootstrapResponse) => void;
  setBackend: (backend: BackendConnectionState) => void;
}

export const useShellStore = create<ShellState>((set) => ({
  activeRoute: "assistant",
  backend: null,
  userDisplayName: "本地用户",
  userStatusLabel: "本地版 · 启动中",
  navigation: {
    pendingSkillCount: 0,
    publishedSkillCount: 0,
    failureCount: 0,
    compositionCount: 0,
  },
  setRoute: (route) => set({ activeRoute: route }),
  hydrate: (bootstrap) =>
    set({
      backend: bootstrap.connection,
      userDisplayName: bootstrap.user.displayName || "本地用户",
      userStatusLabel: bootstrap.user.statusLabel,
      navigation: bootstrap.navigation,
    }),
  setBackend: (backend) => set({ backend }),
}));
