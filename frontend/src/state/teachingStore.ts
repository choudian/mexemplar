import { create } from "zustand";

import {
  confirmTeachingIntent,
  createTeachingRun,
  decideDesktopHealth,
  getTeachingReadiness,
  replyTeachingIntent,
  startTeachingRecording,
  startTeachingTrial,
  stopTeachingRecording,
} from "../api/teaching";
import type { RecordingModeReadiness, TeachingMode, TeachingRun, TeachingStage } from "../api/teaching";
import type { UiEvent } from "../api/client";
import { minimizeWindowForDesktopRecording } from "../api/window";

export type TeachingState = {
  hydrated: boolean;
  readiness: RecordingModeReadiness[];
  selectedMode: TeachingMode | null;
  run: TeachingRun | null;
  stage: TeachingStage;
  intentReply: string;
  progressLog: string[];
  busy: boolean;
  lastError: string | null;
  markHydrated: () => void;
  setError: (message: string | null) => void;
  setSelectedMode: (mode: TeachingMode) => void;
  setIntentReply: (content: string) => void;
  loadReadiness: () => Promise<void>;
  createRun: (mode: TeachingMode) => Promise<void>;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
  decideDesktopHealth: (decision: "continue" | "discard" | "rerecord") => Promise<void>;
  replyIntent: () => Promise<void>;
  confirmIntent: () => Promise<void>;
  startTrial: () => Promise<void>;
  applyEvent: (event: UiEvent) => void;
};

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

export const useTeachingStore = create<TeachingState>((set, get) => ({
  hydrated: false,
  readiness: [],
  selectedMode: null,
  run: null,
  stage: "selecting",
  intentReply: "",
  progressLog: [],
  busy: false,
  lastError: null,
  markHydrated: () => set({ hydrated: true }),
  setError: (message) => set({ lastError: message }),
  setSelectedMode: (mode) => set({ selectedMode: mode }),
  setIntentReply: (content) => set({ intentReply: content }),
  loadReadiness: async () => {
    set({ busy: true, lastError: null });
    try {
      const response = await getTeachingReadiness();
      set({ readiness: response.modes ?? [], hydrated: true });
    } catch (error) {
      set({ lastError: errorMessage(error, "无法加载录制准备状态。") });
    } finally {
      set({ busy: false });
    }
  },
  createRun: async (mode) => {
    set({ busy: true, lastError: null, selectedMode: mode });
    try {
      const run = await createTeachingRun(mode);
      set({ run, stage: run.stage });
    } catch (error) {
      set({ lastError: errorMessage(error, "无法创建教学任务。") });
    } finally {
      set({ busy: false });
    }
  },
  startRecording: async () => {
    const run = get().run;
    const mode = get().selectedMode;
    if (!run || !mode) return;
    set({ busy: true, lastError: null });
    try {
      const isDesktopRecording = mode === "desktop";
      if (isDesktopRecording) {
        await minimizeWindowForDesktopRecording();
      }
      const updated = await startTeachingRecording(run.workflowId, mode, isDesktopRecording);
      set({ run: updated, stage: updated.stage });
    } catch (error) {
      set({ lastError: errorMessage(error, "无法开始录制。") });
    } finally {
      set({ busy: false });
    }
  },
  stopRecording: async () => {
    const run = get().run;
    if (!run) return;
    set({ busy: true, lastError: null });
    try {
      const updated = await stopTeachingRecording(run.workflowId);
      set({ run: updated, stage: updated.stage });
    } catch (error) {
      set({ lastError: errorMessage(error, "无法停止录制。") });
    } finally {
      set({ busy: false });
    }
  },
  decideDesktopHealth: async (decision) => {
    const run = get().run;
    if (!run) return;
    const updated = await decideDesktopHealth(run.workflowId, decision);
    set({ run: updated, stage: updated.stage });
  },
  replyIntent: async () => {
    const run = get().run;
    const content = get().intentReply.trim();
    if (!run || !content) return;
    const updated = await replyTeachingIntent(run.workflowId, content);
    set({ run: updated, stage: updated.stage, intentReply: "" });
  },
  confirmIntent: async () => {
    const run = get().run;
    if (!run) return;
    const updated = await confirmTeachingIntent(run.workflowId);
    set({ run: updated, stage: updated.stage });
  },
  startTrial: async () => {
    const run = get().run;
    if (!run) return;
    const updated = await startTeachingTrial(run.workflowId);
    set({ run: updated, stage: updated.stage });
  },
  applyEvent: (event) => {
    if (event.scope.workflowId && event.scope.workflowId !== get().run?.workflowId) {
      return;
    }
    if (["recording.progress", "teaching.progress", "trial.progress"].includes(event.type)) {
      const payload = event.payload as {
        sourceEvent?: string;
        status?: string;
        headline?: string;
        message?: string;
        error?: string;
        published?: boolean;
      };
      const label = payload.headline ?? payload.message ?? payload.error ?? payload.sourceEvent ?? event.type;
      let nextStage = get().stage;
      if (event.type === "recording.progress" && payload.sourceEvent === "recording_started") {
        nextStage = "recording";
      }
      if (event.type === "recording.progress" && payload.sourceEvent === "recording_stopped") {
        nextStage = "intent_confirmation";
      }
      if (
        event.type === "teaching.progress" &&
        ["requirement_confirmed"].includes(payload.sourceEvent ?? "")
      ) {
        nextStage = "learning";
      }
      if (
        event.type === "teaching.progress" &&
        ["code_completed", "review_passed"].includes(payload.sourceEvent ?? "")
      ) {
        nextStage = "trial_validation";
      }
      if (
        event.type === "teaching.progress" &&
        ["review_failed", "teaching_failure_updated"].includes(payload.sourceEvent ?? "")
      ) {
        nextStage = "failed";
      }
      if (event.type === "trial.progress" && payload.sourceEvent === "trial_success" && payload.published) {
        nextStage = "published";
      }
      if (event.type === "trial.progress" && payload.sourceEvent === "trial_failed") {
        nextStage = "failed";
      }
      set({ progressLog: [...get().progressLog, label], stage: nextStage });
    }
  },
}));
