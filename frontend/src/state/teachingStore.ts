import { create } from "zustand";

import { getSkillTrialHistory, replySkillTrial, startSkillTrial } from "../api/skills";
import {
  createTeachingRun,
  decideDesktopHealth,
  decideTrialPreview,
  getTeachingReadiness,
  getTeachingRun,
  replyTeachingIntent,
  startTeachingRecording,
  startTeachingTrial,
  stopTeachingRecording,
} from "../api/teaching";
import type { RecordingModeReadiness, TeachingMode, TeachingRun, TeachingStage, TrialPreviewRequest } from "../api/teaching";
import type { UiEvent } from "../api/client";
import { isTeachingUiEvent, PROGRESS_EVENT_TYPES } from "../api/uiEvents";
import { minimizeWindowForDesktopRecording } from "../api/window";
import { toErrorMessage } from "./helpers";
import { useSkillsStore } from "./skillsStore";

const MAX_PROGRESS_LOG = 200;
const MAX_MESSAGES = 500;

function makeTrialRun(workflowId: string): TeachingRun {
  return { workflowId, mode: "browser", stage: "trial_validation", summary: {} };
}

export type ChatAgent = "pm" | "trial";

interface AiChatMessage {
  from: "ai";
  agent: ChatAgent;
  headline: string;
  detail?: string;
  error?: boolean;
}

interface UserChatMessage {
  from: "user";
  text: string;
}

export type ChatMessage = AiChatMessage | UserChatMessage;

type TeachingToast = {
  title: string;
  body: string;
};

export type TeachingState = {
  hydrated: boolean;
  readiness: RecordingModeReadiness[];
  selectedMode: TeachingMode | null;
  run: TeachingRun | null;
  stage: TeachingStage;
  progressLog: string[];
  messages: ChatMessage[];
  toast: TeachingToast | null;
  trialPreview: TrialPreviewRequest | null;
  busy: boolean;
  lastError: string | null;
  skillTrialToolId: string | null;
  trialSuccessCount: number;
  markHydrated: () => void;
  setError: (message: string | null) => void;
  dismissToast: () => void;
  setSelectedMode: (mode: TeachingMode) => void;
  loadReadiness: () => Promise<void>;
  createRun: (mode: TeachingMode) => Promise<void>;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<void>;
  decideDesktopHealth: (decision: "continue" | "discard" | "rerecord") => Promise<void>;
  replyIntent: (content: string) => Promise<boolean>;
  startTrial: (task: string) => Promise<boolean>;
  openSkillTrial: (toolId: string) => void;
  closeSkillTrial: () => void;
  refreshCurrentRun: () => Promise<void>;
  decideTrialPreview: (requestId: string, decision: "approve" | "deny") => Promise<void>;
  applyEvent: (event: UiEvent) => void;
};

export function resetToSelecting(): Partial<TeachingState> {
  return {
    run: null,
    stage: "selecting",
    progressLog: [],
    messages: [],
    toast: null,
    trialPreview: null,
    lastError: null,
    busy: false,
  };
}

function clearPreviewIfRequest(preview: TrialPreviewRequest | null, requestId: string): TrialPreviewRequest | null {
  return preview?.requestId === requestId ? null : preview;
}

function previewDecisionError(status: string): string {
  const labels: Record<string, string> = {
    already_resolved: "该试用确认已处理。",
    conflict: "该试用确认已被其它决策处理。",
    expired: "该试用确认已过期。",
  };
  return labels[status] ?? "试用确认未生效。";
}

function appendBounded<T>(array: T[], item: T, max: number): T[] {
  return array.length >= max ? [...array.slice(-max + 1), item] : [...array, item];
}

function labelFromPayload(payload: {
  headline?: string;
  question?: string;
  message?: string;
  error?: string;
  result?: string;
}): string {
  return payload.headline ?? payload.question ?? payload.message ?? payload.error ?? payload.result ?? "";
}

function fallbackProgressLabel(eventType: string, status: string | undefined): string {
  if (eventType === "trial.progress" && status === "running") {
    return "试用正在执行";
  }
  return "";
}

function trialSuccessCountFrom(summary: Record<string, unknown>): number | null {
  const value = summary.trialSuccessCount;
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function dedupeMessageDetail(headline: string, detail: string | undefined): string | undefined {
  return detail && detail !== headline ? detail : undefined;
}

const TRIAL_VALIDATION_TOAST: TeachingToast = {
  title: "技能学习完成",
  body: "可以开始试用验证，确认它能按预期执行。",
};

function toastForStage(stage: TeachingStage): TeachingToast | null {
  return stage === "trial_validation" ? TRIAL_VALIDATION_TOAST : null;
}

export const useTeachingStore = create<TeachingState>((set, get) => ({
  hydrated: false,
  readiness: [],
  selectedMode: null,
  run: null,
  stage: "selecting",
  progressLog: [],
  messages: [],
  toast: null,
  trialPreview: null,
  busy: false,
  lastError: null,
  skillTrialToolId: null,
  trialSuccessCount: 0,
  markHydrated: () => set({ hydrated: true }),
  setError: (message) => set({ lastError: message }),
  dismissToast: () => set({ toast: null }),
  setSelectedMode: (mode) => set({ selectedMode: mode }),
  loadReadiness: async () => {
    set({ busy: true, lastError: null });
    try {
      const response = await getTeachingReadiness();
      set({ readiness: response.modes ?? [], hydrated: true });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载录制准备状态。") });
    } finally {
      set({ busy: false });
    }
  },
  createRun: async (mode) => {
    set({ busy: true, lastError: null, selectedMode: mode });
    try {
      const run = await createTeachingRun(mode);
      set({ run, stage: run.stage, messages: [], progressLog: [], trialPreview: null });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法创建教学任务。") });
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
      set({ lastError: toErrorMessage(error, "无法开始录制。") });
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
      set({ lastError: toErrorMessage(error, "无法停止录制。") });
    } finally {
      set({ busy: false });
    }
  },
  decideDesktopHealth: async (decision) => {
    const run = get().run;
    if (!run) return;
    try {
      const updated = await decideDesktopHealth(run.workflowId, decision);
      set({ run: updated, stage: updated.stage, lastError: null });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法提交录制处理决定。") });
    }
  },
  replyIntent: async (content) => {
    const run = get().run;
    const text = content.trim();
    if (!run || !text) return false;
    set({
      messages: [...get().messages, { from: "user", text }],
      busy: true,
      lastError: null,
    });
    try {
      const updated = await replyTeachingIntent(run.workflowId, text);
      set({ run: updated, stage: updated.stage });
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "发送失败。") });
      return false;
    } finally {
      set({ busy: false });
    }
  },
  startTrial: async (task) => {
    const run = get().run;
    const trialToolId = get().skillTrialToolId;
    if (!run && !trialToolId) return false;
    const text = task.trim();
    if (!text) return false;
    set({ messages: [...get().messages, { from: "user", text }], busy: true, lastError: null });
    try {
      if (trialToolId && run) {
        await replySkillTrial(trialToolId, text);
      } else if (trialToolId) {
        const result = await startSkillTrial(trialToolId);
        if (result.accepted && result.workflowId) {
          set({ run: makeTrialRun(result.workflowId) });
          await replySkillTrial(trialToolId, text);
        }
      } else if (run) {
        const updated = await startTeachingTrial(run.workflowId);
        set({ run: updated, stage: updated.stage });
      }
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "试用启动失败。") });
      return false;
    } finally {
      set({ busy: false });
    }
  },
  openSkillTrial: (toolId) => {
    const allSkills = Object.values(useSkillsStore.getState().categories).flat();
    const skill = allSkills.find((s) => s.toolId === toolId);
    const initialCount = skill?.trialSuccessCount ?? 0;
    const skillWorkflowId = skill?.workflowId ?? null;

    set({
      skillTrialToolId: toolId,
      run: null,
      stage: "trial_validation",
      messages: [],
      progressLog: [],
      trialPreview: null,
      lastError: null,
      busy: true,
      trialSuccessCount: initialCount,
    });

    const startFresh = async () => {
      const result = await startSkillTrial(toolId);
      if (result.accepted && result.workflowId) {
        set({ run: makeTrialRun(result.workflowId) });
      } else {
        set({ lastError: "试用启动被后端拒绝。" });
      }
      set({ busy: false });
    };

    (async () => {
      try {
        if (!skillWorkflowId) {
          await startFresh();
          return;
        }

        const response = await getSkillTrialHistory(toolId);
        const { messages: rawMessages, workflowId: historyWorkflowId } = response;
        const restored: ChatMessage[] = rawMessages.map((msg) =>
          msg.role === "user"
            ? { from: "user" as const, text: msg.content }
            : { from: "ai" as const, agent: "trial" as const, headline: msg.content },
        );
        set({ messages: restored });

        const workflowId = historyWorkflowId ?? skillWorkflowId;
        if (restored.length > 0 && workflowId) {
          set({ run: makeTrialRun(workflowId), busy: false });
          return;
        }
        await startFresh();
      } catch {
        await startFresh();
      }
    })().catch((error) => {
      set({ lastError: toErrorMessage(error, "试用启动失败。"), busy: false });
    });
  },
  closeSkillTrial: () => {
    set({
      ...resetToSelecting(),
      skillTrialToolId: null,
      trialSuccessCount: 0,
    });
  },
  refreshCurrentRun: async () => {
    const run = get().run;
    if (!run) return;
    try {
      const updated = await getTeachingRun(run.workflowId);
      const successCount = trialSuccessCountFrom(updated.summary);
      set({
        run: updated,
        stage: updated.stage,
        lastError: null,
        ...(successCount === null ? {} : { trialSuccessCount: successCount }),
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法刷新当前教学状态，请稍后重试。") });
      throw error;
    }
  },
  decideTrialPreview: async (requestId, decision) => {
    try {
      const result = await decideTrialPreview(requestId, decision);
      if (!result.accepted) {
        set({
          lastError: previewDecisionError(result.status),
          trialPreview: clearPreviewIfRequest(get().trialPreview, requestId),
        });
        return;
      }
      set({
        lastError: null,
        trialPreview: clearPreviewIfRequest(get().trialPreview, requestId),
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法提交试用确认，请重试。") });
    }
  },
  applyEvent: (event) => {
    if (!isTeachingUiEvent(event)) {
      return;
    }
    const state = get();
    const currentRun = state.run;
    const workflowId = event.scope.workflowId;
    if (!currentRun || !workflowId || workflowId !== currentRun.workflowId) return;

    if (event.type === "teaching.stage_changed") {
      const message = event.payload.headline ?? event.payload.message;
      const successCount = event.payload.successCount;
      const toast = toastForStage(event.payload.stage);
      set({
        stage: event.payload.stage,
        run: { ...currentRun, stage: event.payload.stage },
        progressLog: message ? appendBounded(state.progressLog, message, MAX_PROGRESS_LOG) : state.progressLog,
        ...(typeof successCount === "number" ? { trialSuccessCount: successCount } : {}),
        ...(toast ? { toast } : {}),
      });
      return;
    }
    if (event.type === "trial.preview_requested") {
      set({ trialPreview: event.payload });
      return;
    }
    if (event.type === "trial.preview_resolved") {
      set({ trialPreview: clearPreviewIfRequest(state.trialPreview, event.payload.requestId) });
      return;
    }
    if (PROGRESS_EVENT_TYPES.has(event.type)) {
      const payload = event.payload;
      const rawLabel = labelFromPayload(payload);
      const label = rawLabel || fallbackProgressLabel(event.type, payload.status);
      const patch: Partial<TeachingState> = {};
      const isSystemTrialProgress =
        event.type === "trial.progress" && payload.status === "running" && !!rawLabel;

      if (label && !isSystemTrialProgress) {
        patch.progressLog = appendBounded(state.progressLog, label, MAX_PROGRESS_LOG);
      }
      if (event.type === "teaching.progress" || event.type === "trial.progress") {
        const agent: ChatAgent = event.type === "teaching.progress" ? "pm" : "trial";
        const headline = label;
        const detail =
          event.type === "trial.progress"
            ? event.payload.message ?? event.payload.result
            : event.payload.message;
        if (headline && !isSystemTrialProgress) {
          patch.messages = appendBounded(
            state.messages,
            {
              from: "ai",
              agent,
              headline,
              detail: dedupeMessageDetail(headline, detail),
              error: !!payload.error,
            },
            MAX_MESSAGES,
          );
        }
      }
      if (event.type === "trial.progress") {
        const trialPayload = event.payload;
        if (typeof trialPayload.successCount === "number") {
          patch.trialSuccessCount = trialPayload.successCount;
        }
        if (trialPayload.published) {
          patch.stage = "published";
          patch.run = { ...currentRun, stage: "published" };
        }
        if (state.skillTrialToolId && state.busy) {
          patch.busy = false;
        }
      }
      if (Object.keys(patch).length > 0) set(patch);
    }
  },
}));
