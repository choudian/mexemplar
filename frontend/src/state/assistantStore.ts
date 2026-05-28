import { create } from "zustand";

import {
  createAssistantSession,
  decideAssistantConfirmation,
  deleteAssistantSession,
  listAssistantMessages,
  listAssistantSessions,
  renameAssistantSession,
  sendAssistantMessage,
  setAssistantAutoApprove,
  triggerAssistantSegmentBoundary,
  triggerAssistantSegmentIdle,
} from "../api/assistant";
import type { AssistantConfirmation, AssistantMessage, AssistantSession } from "../api/assistant";
import type { UiEvent } from "../api/client";

async function sealPreviousSegment(prevSessionId: string | null): Promise<void> {
  if (prevSessionId) {
    try { await triggerAssistantSegmentBoundary(prevSessionId, "new_session"); } catch { /* best-effort */ }
  }
}
import { toErrorMessage } from "./helpers";

let _idleTimerRef: ReturnType<typeof setTimeout> | null = null;
let _optimisticMessageCounter = 0;

type AssistantProgress = {
  status: "idle" | "running" | "waiting_for_user" | "succeeded" | "failed";
  headline: string;
};

export type PendingAssistantMessage = Omit<AssistantMessage, "sequence"> & {
  optimisticId: string;
  sessionId: string;
};

export type AssistantState = {
  hydrated: boolean;
  sessions: AssistantSession[];
  activeSessionId: string | null;
  messages: AssistantMessage[];
  query: string;
  draft: string;
  loadingSessions: boolean;
  loadingMessages: boolean;
  sending: boolean;
  hasMoreBefore: boolean;
  nextBeforeSequence: number | null;
  progress: AssistantProgress;
  confirmations: AssistantConfirmation[];
  lastError: string | null;
  idleThresholdMs: number | null;
  autoApprove: boolean;
  pendingOptimisticMessages: PendingAssistantMessage[];
  markHydrated: () => void;
  setError: (message: string | null) => void;
  setQuery: (query: string) => void;
  setDraft: (draft: string) => void;
  setIdleThresholdSeconds: (seconds: number) => void;
  loadSessions: () => Promise<void>;
  createSession: () => Promise<string>;
  selectSession: (sessionId: string) => Promise<void>;
  loadMoreBefore: () => Promise<void>;
  renameSession: (sessionId: string, title: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  sendDraft: () => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  decideConfirmation: (requestId: string, decision: "approve" | "deny") => Promise<void>;
  setAutoApprove: (enabled: boolean) => Promise<void>;
  resetIdleTimer: () => void;
  clearIdleTimer: () => void;
};

const idleProgress: AssistantProgress = { status: "idle", headline: "" };

function uniqueMessages(messages: AssistantMessage[]): AssistantMessage[] {
  const bySequence = new Map<number, AssistantMessage>();
  for (const message of messages) {
    bySequence.set(message.sequence, message);
  }
  return Array.from(bySequence.values()).sort((a, b) => a.sequence - b.sequence);
}

function nextOptimisticId(): string {
  _optimisticMessageCounter += 1;
  return `optimistic_${_optimisticMessageCounter}`;
}

function removePendingOptimisticMessage(
  messages: PendingAssistantMessage[],
  optimisticId: string | null,
): PendingAssistantMessage[] {
  if (optimisticId === null) {
    return messages;
  }
  return messages.filter((message) => message.optimisticId !== optimisticId);
}

function isPendingEcho(
  pending: PendingAssistantMessage,
  sessionId: string,
  message: AssistantMessage,
): boolean {
  return (
    pending.sessionId === sessionId
    && message.role === "user"
    && pending.content.trim() === message.content.trim()
  );
}

function reconcilePendingMessages(
  pendingMessages: PendingAssistantMessage[],
  sessionId: string,
  authoritativeMessages: AssistantMessage[],
): PendingAssistantMessage[] {
  let remaining = pendingMessages;
  for (const message of authoritativeMessages) {
    const index = remaining.findIndex((pending) => isPendingEcho(pending, sessionId, message));
    if (index === -1) {
      continue;
    }
    remaining = remaining.filter((_, currentIndex) => currentIndex !== index);
  }
  return remaining;
}

export const useAssistantStore = create<AssistantState>((set, get) => ({
  hydrated: false,
  sessions: [],
  activeSessionId: null,
  messages: [],
  query: "",
  draft: "",
  loadingSessions: false,
  loadingMessages: false,
  sending: false,
  hasMoreBefore: false,
  nextBeforeSequence: null,
  progress: idleProgress,
  confirmations: [],
  lastError: null,
  idleThresholdMs: null,
  autoApprove: false,
  pendingOptimisticMessages: [],
  markHydrated: () => set({ hydrated: true }),
  setError: (message) => set({ lastError: message }),
  setQuery: (query) => set({ query }),
  setDraft: (draft) => set({ draft }),
  setIdleThresholdSeconds: (seconds) => {
    const threshold = Number.isFinite(seconds) && seconds > 0 ? seconds * 1000 : null;
    set({ idleThresholdMs: threshold });
  },
  loadSessions: async () => {
    set({ loadingSessions: true, lastError: null });
    try {
      const sessions = await listAssistantSessions(get().query);
      set({ sessions, hydrated: true });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载对话列表。") });
    } finally {
      set({ loadingSessions: false });
    }
  },
  createSession: async () => {
    const prevSessionId = get().activeSessionId;
    await sealPreviousSegment(prevSessionId);
    const sessionId = await createAssistantSession();
    set({
      activeSessionId: sessionId,
      messages: [],
      draft: "",
      progress: idleProgress,
      confirmations: [],
      autoApprove: false,
    });
    get().clearIdleTimer();
    await get().loadSessions();
    return sessionId;
  },
  selectSession: async (sessionId) => {
    const prevSessionId = get().activeSessionId;
    get().clearIdleTimer();
    if (prevSessionId && prevSessionId !== sessionId) {
      await sealPreviousSegment(prevSessionId);
    }
    set({ activeSessionId: sessionId, loadingMessages: true, lastError: null });
    try {
      const page = await listAssistantMessages(sessionId, { limit: 10 });
      set({
        messages: page.items,
        hasMoreBefore: page.hasMoreBefore,
        nextBeforeSequence: page.nextBeforeSequence,
        progress: idleProgress,
        pendingOptimisticMessages: reconcilePendingMessages(
          get().pendingOptimisticMessages,
          sessionId,
          page.items,
        ),
        confirmations: get().confirmations.filter((item) => item.sessionId === sessionId),
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载对话消息。") });
    } finally {
      set({ loadingMessages: false });
    }
  },
  loadMoreBefore: async () => {
    const { activeSessionId, hasMoreBefore, loadingMessages, nextBeforeSequence } = get();
    if (!activeSessionId || !hasMoreBefore || nextBeforeSequence === null || loadingMessages) {
      return;
    }
    set({ loadingMessages: true, lastError: null });
    try {
      const page = await listAssistantMessages(activeSessionId, {
        limit: 10,
        beforeSequence: nextBeforeSequence,
      });
      set({
        messages: uniqueMessages([...page.items, ...get().messages]),
        hasMoreBefore: page.hasMoreBefore,
        nextBeforeSequence: page.nextBeforeSequence,
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载更早消息。") });
    } finally {
      set({ loadingMessages: false });
    }
  },
  renameSession: async (sessionId, title) => {
    const updated = await renameAssistantSession(sessionId, title);
    set({
      sessions: get().sessions.map((session) => (session.sessionId === sessionId ? updated : session)),
    });
  },
  deleteSession: async (sessionId) => {
    await deleteAssistantSession(sessionId);
    set({
      sessions: get().sessions.filter((session) => session.sessionId !== sessionId),
      activeSessionId: get().activeSessionId === sessionId ? null : get().activeSessionId,
      messages: get().activeSessionId === sessionId ? [] : get().messages,
      pendingOptimisticMessages: get().pendingOptimisticMessages.filter(
        (message) => message.sessionId !== sessionId,
      ),
      confirmations:
        get().activeSessionId === sessionId
          ? []
          : get().confirmations.filter((item) => item.sessionId !== sessionId),
    });
  },
  sendDraft: async () => {
    const content = get().draft;
    if (!content.trim() || get().sending) {
      return;
    }

    let sessionId = get().activeSessionId;
    let optimisticId: string | null = null;
    set({ sending: true, lastError: null, progress: { status: "running", headline: "正在处理" } });
    try {
      if (!sessionId) {
        sessionId = await get().createSession();
      }
      optimisticId = nextOptimisticId();
      const optimistic: PendingAssistantMessage = {
        optimisticId,
        sessionId,
        role: "user",
        content,
        createdAt: new Date().toISOString(),
        rendering: "plain_text",
      };
      set({
        draft: "",
        pendingOptimisticMessages: [...get().pendingOptimisticMessages, optimistic],
      });
      const result = await sendAssistantMessage(sessionId, content);
      if (!result.accepted) {
        const state = get();
        set({
          draft: state.activeSessionId === sessionId ? content : state.draft,
          pendingOptimisticMessages: removePendingOptimisticMessage(
            state.pendingOptimisticMessages,
            optimisticId,
          ),
          progress: { status: "waiting_for_user", headline: "上一条消息仍在处理中" },
        });
      }
    } catch (error) {
      const state = get();
      set({
        draft: state.activeSessionId === sessionId ? content : state.draft,
        pendingOptimisticMessages: removePendingOptimisticMessage(
          state.pendingOptimisticMessages,
          optimisticId,
        ),
        lastError: toErrorMessage(error, "消息发送失败。"),
      });
    } finally {
      set({ sending: false });
      get().resetIdleTimer();
    }
  },
  applyEvent: (event) => {
    if (event.scope.sessionId && event.scope.sessionId !== get().activeSessionId) {
      return;
    }
    if (event.type === "assistant.message") {
      const message = event.payload as unknown as AssistantMessage;
      const eventSessionId = event.scope.sessionId ?? "";
      set({
        messages: uniqueMessages([...get().messages, message]),
        pendingOptimisticMessages: reconcilePendingMessages(
          get().pendingOptimisticMessages,
          eventSessionId,
          [message],
        ),
      });
      return;
    }
    if (event.type === "assistant.progress") {
      const payload = event.payload as { status?: AssistantProgress["status"]; headline?: string };
      set({
        progress: {
          status: payload.status ?? "running",
          headline: payload.headline ?? "",
        },
      });
      return;
    }
    if (event.type === "assistant.error") {
      const payload = event.payload as { message?: string };
      set({
        progress: { status: "failed", headline: payload.message ?? "Assistant 处理失败" },
        lastError: payload.message ?? "Assistant 处理失败",
      });
      return;
    }
    if (event.type === "assistant.confirmation") {
      const confirmation = event.payload as unknown as AssistantConfirmation;
      set({
        confirmations: [
          ...get().confirmations.filter((item) => item.requestId !== confirmation.requestId),
          confirmation,
        ],
      });
    }
  },
  decideConfirmation: async (requestId, decision) => {
    await decideAssistantConfirmation(requestId, decision);
    set({
      confirmations: get().confirmations.filter((confirmation) => confirmation.requestId !== requestId),
    });
  },
  setAutoApprove: async (enabled) => {
    const previous = get().autoApprove;
    set({ autoApprove: enabled });
    try {
      await setAssistantAutoApprove(enabled);
      if (enabled) {
        set({ confirmations: [] });
      }
    } catch (error) {
      set({ autoApprove: previous, lastError: toErrorMessage(error, "设置免确认失败。") });
    }
  },
  resetIdleTimer: () => {
    if (_idleTimerRef) {
      clearTimeout(_idleTimerRef);
    }
    const state = get();
    const { idleThresholdMs, activeSessionId: sessionId } = state;
    if (!sessionId || idleThresholdMs === null) return;
    _idleTimerRef = setTimeout(async () => {
      if (get().activeSessionId !== sessionId) return;
      try {
        await triggerAssistantSegmentIdle(sessionId);
      } catch {
        // Idle trigger is best-effort; failures are non-critical
      }
    }, idleThresholdMs);
  },
  clearIdleTimer: () => {
    if (_idleTimerRef) {
      clearTimeout(_idleTimerRef);
      _idleTimerRef = null;
    }
  },
}));
