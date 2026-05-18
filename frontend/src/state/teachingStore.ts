import { create } from "zustand";

import { getSkillTrialHistory, replySkillTrial, startSkillTrial } from "../api/skills";
import {
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
import { useSkillsStore } from "./skillsStore";
import { toErrorMessage } from "./helpers";

// ── Chat message types ────────────────────────────────────────────────────

function makeTrialRun(workflowId: string): TeachingRun {
  return { workflowId, mode: "browser", stage: "trial_validation", summary: {} };
}

export type ChatAgent = "pm" | "trial";

export interface AiChatMessage {
  from: "ai";
  agent: ChatAgent;
  headline: string;
  detail?: string;
  error?: boolean;
}

export interface UserChatMessage {
  from: "user";
  text: string;
}

export type ChatMessage = AiChatMessage | UserChatMessage;

// ── Store ─────────────────────────────────────────────────────────────────

const SYSTEM_TRIAL_EVENTS = new Set(["trial_requested", "trial_failed", "trial_success"]);

const TEACHING_RELEVANT_EVENTS = new Set([
  "recording.progress",
  "teaching.progress",
  "trial.progress",
  "skills.changed",
]);

const PROGRESS_EVENTS = new Set([
  "recording.progress",
  "teaching.progress",
  "trial.progress",
]);

export type TeachingToast = {
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
  replyIntent: (content: string) => Promise<void>;
  startTrial: (task: string) => Promise<void>;
  openSkillTrial: (toolId: string) => void;
  closeSkillTrial: () => void;
  applyEvent: (event: UiEvent) => void;
};

export function resetToSelecting(): Partial<TeachingState> {
  return {
    run: null,
    stage: "selecting",
    progressLog: [],
    messages: [],
    lastError: null,
    busy: false,
  };
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
      set({ run, stage: run.stage });
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
    const updated = await decideDesktopHealth(run.workflowId, decision);
    set({ run: updated, stage: updated.stage });
  },
  replyIntent: async (content) => {
    const run = get().run;
    const text = content.trim();
    if (!run || !text) return;
    set({
      messages: [...get().messages, { from: "user", text }],
      busy: true,
      lastError: null,
    });
    try {
      const updated = await replyTeachingIntent(run.workflowId, text);
      set({ run: updated, stage: updated.stage });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "发送失败。") });
    } finally {
      set({ busy: false });
    }
  },
  startTrial: async (task) => {
    const run = get().run;
    const trialToolId = get().skillTrialToolId;
    if (!run && !trialToolId) return;
    const text = task.trim();
    if (!text) return;
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
    } catch (error) {
      set({ lastError: toErrorMessage(error, "试用启动失败。") });
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
        // No prior workflow — skip history lookup, start fresh directly
        if (!skillWorkflowId) {
          await startFresh();
          return;
        }

        const response = await getSkillTrialHistory(toolId);
        const { messages: rawMessages, workflowId: historyWorkflowId } = response;

        // Backend returns "assistant" role; frontend uses "ai" internally
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
  applyEvent: (event) => {
    if (!TEACHING_RELEVANT_EVENTS.has(event.type)) {
      return;
    }
    const state = get();
    const isToolSaved = event.type === "skills.changed" && event.payload.sourceEvent === "tool_saved";
    const isToolPublished = event.type === "skills.changed" && event.payload.sourceEvent === "tool_published";

    const isSkillTrial = !!state.skillTrialToolId;
    if (!isToolSaved && !isToolPublished && !isSkillTrial && event.scope.workflowId && event.scope.workflowId !== state.run?.workflowId) {
      return;
    }

    const patch: Partial<TeachingState> = {};

    if (isToolPublished) {
      patch.stage = "published";
    }

    if (isToolSaved && !state.skillTrialToolId) {
      patch.toast = { title: "技能学习完成", body: "新技能已就绪，可以在 AI 助手中使用。" };
    }

    if (PROGRESS_EVENTS.has(event.type)) {
      if (event.type === "trial.progress" && state.skillTrialToolId && state.busy) {
        patch.busy = false;
      }
      const payload = event.payload as {
        sourceEvent?: string;
        status?: string;
        headline?: string;
        message?: string;
        error?: string;
        published?: boolean;
        success_count?: number;
      };
      const label = payload.headline ?? payload.message ?? payload.error ?? payload.sourceEvent ?? event.type;

      const agent: ChatAgent | null =
        event.type === "teaching.progress" ? "pm"
        : event.type === "trial.progress" ? "trial"
        : null;

      const isTrialSystemEvent = agent === "trial" && (
        SYSTEM_TRIAL_EVENTS.has(payload.sourceEvent ?? "") ||
        payload.status === "running"
      );

      const aiMsg: AiChatMessage | null = agent && !isTrialSystemEvent ? {
        from: "ai",
        agent,
        headline: payload.headline ?? payload.sourceEvent ?? event.type,
        detail: payload.message ?? undefined,
        error: !!payload.error,
      } : null;

      if (aiMsg) {
        patch.messages = [...state.messages, aiMsg];
      }
      if (!isTrialSystemEvent) {
        patch.progressLog = [...state.progressLog, label];
      }

      let nextStage = patch.stage ?? state.stage;
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
        ["review_failed", "teaching_failure_updated"].includes(payload.sourceEvent ?? "")
      ) {
        nextStage = "failed";
      }

      if (event.type === "trial.progress" && payload.sourceEvent === "trial_success") {
        if (typeof payload.success_count === "number") {
          patch.trialSuccessCount = payload.success_count;
        }
        if (payload.published) {
          nextStage = "published";
        }
      }
      patch.stage = nextStage;
    }

    if (Object.keys(patch).length > 0) {
      set(patch);
    }
  },
}));
