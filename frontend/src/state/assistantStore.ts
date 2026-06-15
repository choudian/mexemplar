import { create } from "zustand";

import {
  createAssistantSession,
  decideAssistantConfirmation,
  deleteAssistantSession,
  getSubagentTranscript,
  listAssistantMessages,
  listAssistantSessions,
  listSubagents,
  renameAssistantSession,
  retryAssistantMessage,
  sendAssistantMessage,
  setAssistantAutoApprove,
  stopAssistantRun,
  triggerAssistantSegmentBoundary,
  triggerAssistantSegmentIdle,
} from "../api/assistant";
import type { AssistantConfirmation, AssistantMessage, AssistantSession } from "../api/assistant";
import type { UiEvent } from "../api/client";
import { toErrorMessage } from "./helpers";

import { idleProgress } from "./assistantTypes";
import type {
  ActivityStep,
  AssistantProgress,
  AssistantTurnActivity,
  PendingAssistantMessage,
  QueuedMessage,
  Subagent,
} from "./assistantTypes";
import {
  appendActivityStep,
  beginOptimisticTurn,
  commitLiveTurn,
  emptyTurn,
  getTurn,
  isPendingEcho,
  latestVisibleTurnId,
  migrateTurn,
  reconcilePendingMessages,
  resolveTurnId,
  rollbackOptimisticTurn,
  syncTurnsFromMessages,
  turnIdFromSequence,
  uniqueMessages,
  updateTurn,
  upsertSubagent,
} from "./assistantHelpers";

// Re-export types and helpers for consumers that import from assistantStore
export type { ActivityStepKind, ActivityStep, AssistantTurnActivity, PendingAssistantMessage, QueuedMessage, QueuedMessageState, Subagent } from "./assistantTypes";
export { emptyTurn, turnIdFromMessage } from "./assistantHelpers";

async function sealPreviousSegment(prevSessionId: string | null): Promise<void> {
  if (prevSessionId) {
    try { await triggerAssistantSegmentBoundary(prevSessionId, "new_session"); } catch { /* best-effort */ }
  }
}

let _idleTimerRef: ReturnType<typeof setTimeout> | null = null;

// 前端实时活动步骤上限：与后端单回合上限呼应，防极端长回合刷爆 store
const MAX_LIVE_ACTIVITY_STEPS = 300;

export type AssistantState = {
  hydrated: boolean;
  sessions: AssistantSession[];
  activeSessionId: string | null;
  messages: AssistantMessage[];
  query: string;
  draft: string;
  draftBySession: Record<string, string>;
  loadingSessions: boolean;
  loadingMessages: boolean;
  sending: boolean;
  // "停止中"过渡态（点击停止到 cancelled 进度到达前），驱动幂等反馈
  stopping: boolean;
  hasMoreBefore: boolean;
  nextBeforeSequence: number | null;
  progress: AssistantProgress;
  progressBySession: Record<string, AssistantProgress>;
  stoppingBySession: Record<string, boolean>;
  confirmations: AssistantConfirmation[];
  lastError: string | null;
  idleThresholdMs: number | null;
  autoApprove: boolean;
  pendingOptimisticMessages: PendingAssistantMessage[];
  // === 014 生产态字段（实时过程 / 子任务卡片 / 排队消息）===
  // 过程与子任务按 sessionId + turnId 双层归属，避免多回合历史混在同一个 session 时间线里。
  turnActivityBySession: Record<string, Record<string, AssistantTurnActivity>>;
  // 当前正在运行或刚提交的回合；事件未携带 runId 时作为实时事件归属边界。
  activeTurnIdBySession: Record<string, string>;
  // 每会话至多一条排队消息；跨会话切换保留，不持久化到后端。
  queuedMessageBySession: Record<string, QueuedMessage>;
  retryingFailureBySession: Record<string, number>;
  markHydrated: () => void;
  setError: (message: string | null) => void;
  setQuery: (query: string) => void;
  setDraft: (draft: string) => void;
  setIdleThresholdSeconds: (seconds: number) => void;
  loadSessions: () => Promise<void>;
  createSession: () => Promise<string | null>;
  // 点"新对话"：仅切到空白草稿态，不写后端；首次发送时由 sendDraft 惰性创建会话。
  startNewConversation: () => Promise<void>;
  selectSession: (sessionId: string) => Promise<void>;
  loadMoreBefore: () => Promise<void>;
  renameSession: (sessionId: string, title: string) => Promise<void>;
  deleteSession: (sessionId: string) => Promise<void>;
  sendDraft: () => Promise<void>;
  stopRun: () => Promise<void>;
  // 排队消息状态机（US2）：running 时输入即 editing；回车/失焦 → queued；双击 → editing。
  setQueuedText: (text: string) => void;
  commitQueued: () => void;
  editQueued: () => void;
  // 取消排队：清除当前会话的排队/编辑中消息（不外发、不留痕）
  cancelQueued: () => void;
  // 子任务权威列表兜底（US4）：重连/打开会话时拉权威态
  refreshSubagents: (sessionId: string) => Promise<void>;
  // 过程权威 transcript 兜底（FR-032）：事件缺口时刷新当前回合步骤
  refreshActivityTranscript: (sessionId: string, turnId?: string) => Promise<void>;
  // 继续暂停子任务（US5）：经主助理消息派发唤醒续跑（守 100% 调度，不新增端点）
  continueSubagent: (sessionId: string, subagentId: string, supplemental?: string) => Promise<void>;
  retryFailedMessage: (
    sessionId: string,
    messageSequence: number,
    content?: string,
  ) => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  decideConfirmation: (requestId: string, decision: "approve" | "deny") => Promise<void>;
  setAutoApprove: (enabled: boolean) => Promise<void>;
  resetIdleTimer: () => void;
  clearIdleTimer: () => void;
};

export const useAssistantStore = create<AssistantState>((set, get) => ({
  hydrated: false,
  sessions: [],
  activeSessionId: null,
  messages: [],
  query: "",
  draft: "",
  draftBySession: {},
  loadingSessions: false,
  loadingMessages: false,
  sending: false,
  stopping: false,
  hasMoreBefore: false,
  nextBeforeSequence: null,
  progress: idleProgress,
  progressBySession: {},
  stoppingBySession: {},
  confirmations: [],
  lastError: null,
  idleThresholdMs: null,
  autoApprove: false,
  pendingOptimisticMessages: [],
  turnActivityBySession: {},
  activeTurnIdBySession: {},
  queuedMessageBySession: {},
  retryingFailureBySession: {},
  markHydrated: () => set({ hydrated: true }),
  setError: (message) => set({ lastError: message }),
  setQuery: (query) => set({ query }),
  setDraft: (draft) => {
    const sessionId = get().activeSessionId;
    set({
      draft,
      draftBySession: sessionId
        ? { ...get().draftBySession, [sessionId]: draft }
        : get().draftBySession,
    });
  },
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
    set({ lastError: null });
    try {
      await sealPreviousSegment(prevSessionId);
      const sessionId = await createAssistantSession();
      set({
        activeSessionId: sessionId,
        messages: [],
        draft: "",
        draftBySession: { ...get().draftBySession, [sessionId]: "" },
        progress: idleProgress,
        progressBySession: { ...get().progressBySession, [sessionId]: idleProgress },
        stopping: false,
        stoppingBySession: { ...get().stoppingBySession, [sessionId]: false },
        confirmations: [],
        autoApprove: false,
        activeTurnIdBySession: { ...get().activeTurnIdBySession, [sessionId]: "" },
        turnActivityBySession: { ...get().turnActivityBySession, [sessionId]: {} },
      });
      get().clearIdleTimer();
      await get().loadSessions();
      return sessionId;
    } catch (error) {
      set({
        lastError: toErrorMessage(error, "无法新建对话。"),
        progress: idleProgress,
      });
      return null;
    }
  },
  startNewConversation: async () => {
    const prevSessionId = get().activeSessionId;
    get().clearIdleTimer();
    // 与切换/新建一致：先封存上一会话的 Segment（reason=new_session），再切到空白草稿态。
    await sealPreviousSegment(prevSessionId);
    set({
      activeSessionId: null,
      messages: [],
      draft: "",
      progress: idleProgress,
      stopping: false,
      confirmations: [],
      autoApprove: false,
      lastError: null,
      hasMoreBefore: false,
      nextBeforeSequence: null,
    });
  },
  selectSession: async (sessionId) => {
    const prevSessionId = get().activeSessionId;
    const currentDraft = get().draft;
    get().clearIdleTimer();
    if (prevSessionId && prevSessionId !== sessionId) {
      await sealPreviousSegment(prevSessionId);
    }
    set({ activeSessionId: sessionId, loadingMessages: true, lastError: null });
    try {
      const page = await listAssistantMessages(sessionId, { limit: 10 });
      const existingTurns = get().turnActivityBySession[sessionId] ?? {};
      const syncedTurns = syncTurnsFromMessages(page.items, existingTurns);
      const latestTurnId = latestVisibleTurnId(
        sessionId,
        page.items,
        get().pendingOptimisticMessages,
      );
      set({
        messages: page.items,
        hasMoreBefore: page.hasMoreBefore,
        nextBeforeSequence: page.nextBeforeSequence,
        draft: get().draftBySession[sessionId] ?? "",
        draftBySession: prevSessionId
          ? { ...get().draftBySession, [prevSessionId]: currentDraft }
          : get().draftBySession,
        progress: get().progressBySession[sessionId] ?? idleProgress,
        stopping: Boolean(get().stoppingBySession[sessionId]),
        pendingOptimisticMessages: reconcilePendingMessages(
          get().pendingOptimisticMessages,
          sessionId,
          page.items,
        ),
        confirmations: get().confirmations.filter((item) => item.sessionId === sessionId),
        turnActivityBySession: {
          ...get().turnActivityBySession,
          [sessionId]: syncedTurns,
        },
        activeTurnIdBySession: latestTurnId
          ? { ...get().activeTurnIdBySession, [sessionId]: latestTurnId }
          : get().activeTurnIdBySession,
      });
      // 子任务权威列表兜底（重开会话恢复卡片与状态）
      void get().refreshSubagents(sessionId);
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
      const mergedMessages = uniqueMessages([...page.items, ...get().messages]);
      set({
        messages: mergedMessages,
        hasMoreBefore: page.hasMoreBefore,
        nextBeforeSequence: page.nextBeforeSequence,
        turnActivityBySession: {
          ...get().turnActivityBySession,
          [activeSessionId]: syncTurnsFromMessages(
            mergedMessages,
            get().turnActivityBySession[activeSessionId] ?? {},
          ),
        },
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载更早消息。") });
    } finally {
      set({ loadingMessages: false });
    }
  },
  renameSession: async (sessionId, title) => {
    try {
      const updated = await renameAssistantSession(sessionId, title);
      set({
        sessions: get().sessions.map((session) => (session.sessionId === sessionId ? updated : session)),
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "重命名对话失败。") });
    }
  },
  deleteSession: async (sessionId) => {
    try {
      await deleteAssistantSession(sessionId);
    } catch (error) {
      set({ lastError: toErrorMessage(error, "删除对话失败。") });
      return;
    }
    const nextTurnActivity = { ...get().turnActivityBySession };
    delete nextTurnActivity[sessionId];
    const nextActiveTurns = { ...get().activeTurnIdBySession };
    delete nextActiveTurns[sessionId];
    const nextDrafts = { ...get().draftBySession };
    delete nextDrafts[sessionId];
    const nextProgress = { ...get().progressBySession };
    delete nextProgress[sessionId];
    const nextStopping = { ...get().stoppingBySession };
    delete nextStopping[sessionId];
    const nextRetryingFailures = { ...get().retryingFailureBySession };
    delete nextRetryingFailures[sessionId];
    set({
      sessions: get().sessions.filter((session) => session.sessionId !== sessionId),
      activeSessionId: get().activeSessionId === sessionId ? null : get().activeSessionId,
      messages: get().activeSessionId === sessionId ? [] : get().messages,
      draft: get().activeSessionId === sessionId ? "" : get().draft,
      draftBySession: nextDrafts,
      progress: get().activeSessionId === sessionId ? idleProgress : get().progress,
      progressBySession: nextProgress,
      stopping: get().activeSessionId === sessionId ? false : get().stopping,
      stoppingBySession: nextStopping,
      retryingFailureBySession: nextRetryingFailures,
      turnActivityBySession: nextTurnActivity,
      activeTurnIdBySession: nextActiveTurns,
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
    set({ sending: true, lastError: null });
    try {
      if (!sessionId) {
        sessionId = await get().createSession();
        if (!sessionId) return;
      }
      const runningProgress: AssistantProgress = { status: "running", headline: "正在处理" };
      const begun = beginOptimisticTurn(get(), sessionId, content);
      optimisticId = begun.optimisticId;
      set({
        draft: "",
        draftBySession: { ...get().draftBySession, [sessionId]: "" },
        progress: get().activeSessionId === sessionId ? runningProgress : get().progress,
        progressBySession: { ...get().progressBySession, [sessionId]: runningProgress },
        stoppingBySession: { ...get().stoppingBySession, [sessionId]: false },
        stopping: get().activeSessionId === sessionId ? false : get().stopping,
        ...begun.patch,
      });
      const result = await sendAssistantMessage(sessionId!, content);
      if (!result.accepted) {
        const busyProgress: AssistantProgress = { status: "running", headline: "上一条消息仍在处理中" };
        set({
          draft: get().activeSessionId === sessionId ? content : get().draft,
          draftBySession: { ...get().draftBySession, [sessionId]: content },
          ...rollbackOptimisticTurn(get(), sessionId, optimisticId),
          progress: get().activeSessionId === sessionId ? busyProgress : get().progress,
          progressBySession: { ...get().progressBySession, [sessionId]: busyProgress },
        });
      }
    } catch (error) {
      set({
        draft: get().activeSessionId === sessionId ? content : get().draft,
        ...(sessionId ? { draftBySession: { ...get().draftBySession, [sessionId]: content } } : {}),
        ...(sessionId && optimisticId ? rollbackOptimisticTurn(get(), sessionId, optimisticId) : {}),
        lastError: toErrorMessage(error, "消息发送失败。"),
      });
    } finally {
      set({ sending: false });
      get().resetIdleTimer();
    }
  },
  stopRun: async () => {
    const sessionId = get().activeSessionId;
    if (!sessionId) return;
    // 幂等：生效前重复点击不重复取消、不报错；仅运行中可停止
    const progress = get().progressBySession[sessionId] ?? get().progress;
    if (get().stoppingBySession[sessionId] || progress.status !== "running") return;
    set({
      stopping: true,
      stoppingBySession: { ...get().stoppingBySession, [sessionId]: true },
    });
    try {
      const result = await stopAssistantRun(sessionId, progress.runId);
      if (!result.accepted) {
        const nextStopping = { ...get().stoppingBySession, [sessionId]: false };
        const nextProgressBySession = { ...get().progressBySession, [sessionId]: idleProgress };
        set({
          stopping: get().activeSessionId === sessionId ? false : get().stopping,
          stoppingBySession: nextStopping,
          progress: get().activeSessionId === sessionId ? idleProgress : get().progress,
          progressBySession: nextProgressBySession,
          lastError: "当前没有正在处理的请求。",
        });
        void get().refreshSubagents(sessionId);
        void get().refreshActivityTranscript(sessionId);
      }
    } catch (error) {
      set({
        stopping: get().activeSessionId === sessionId ? false : get().stopping,
        stoppingBySession: { ...get().stoppingBySession, [sessionId]: false },
        lastError: toErrorMessage(error, "停止失败，请重试。"),
      });
    }
  },
  setQueuedText: (text) => {
    const sessionId = get().activeSessionId;
    if (!sessionId) return;
    const map = { ...get().queuedMessageBySession };
    if (text.length === 0) {
      delete map[sessionId];
    } else {
      // 输入即进入编辑态（每会话仅一条：再写改同一条）
      map[sessionId] = { text, state: "editing" };
    }
    set({ queuedMessageBySession: map });
  },
  commitQueued: () => {
    const sessionId = get().activeSessionId;
    if (!sessionId) return;
    const current = get().queuedMessageBySession[sessionId];
    if (!current || !current.text.trim() || current.state === "queued") return;
    set({
      queuedMessageBySession: {
        ...get().queuedMessageBySession,
        [sessionId]: { ...current, state: "queued" },
      },
    });
  },
  editQueued: () => {
    const sessionId = get().activeSessionId;
    if (!sessionId) return;
    const current = get().queuedMessageBySession[sessionId];
    if (!current || current.state === "editing") return;
    set({
      queuedMessageBySession: {
        ...get().queuedMessageBySession,
        [sessionId]: { ...current, state: "editing" },
      },
    });
  },
  cancelQueued: () => {
    const sessionId = get().activeSessionId;
    if (!sessionId) return;
    if (!get().queuedMessageBySession[sessionId]) return;
    const map = { ...get().queuedMessageBySession };
    delete map[sessionId];
    set({ queuedMessageBySession: map });
  },
  continueSubagent: async (sessionId, subagentId, supplemental) => {
    // 只允许继续本会话子任务：调用方传入当前会话的卡片标识
    const note = (supplemental ?? "").trim();
    const content = note
      ? `请继续把刚才暂停的子任务做完。补充说明：${note}`
      : "请继续把刚才暂停的子任务做完。";
    const runningProgress: AssistantProgress = { status: "running", headline: "正在处理" };
    set({
      progress: get().activeSessionId === sessionId ? runningProgress : get().progress,
      progressBySession: { ...get().progressBySession, [sessionId]: runningProgress },
      lastError: null,
    });
    const begun = beginOptimisticTurn(get(), sessionId, content);
    const optimisticId = begun.optimisticId;
    try {
      set(begun.patch);
      const result = await sendAssistantMessage(sessionId, content, {
        continueSubagent: { subagentId, ...(note ? { supplemental: note } : {}) },
      });
      if (!result.accepted) {
        const busyProgress: AssistantProgress = { status: "running", headline: "上一条消息仍在处理中" };
        set({
          ...rollbackOptimisticTurn(get(), sessionId, optimisticId),
          progress: get().activeSessionId === sessionId ? busyProgress : get().progress,
          progressBySession: { ...get().progressBySession, [sessionId]: busyProgress },
        });
      }
    } catch (error) {
      set({
        ...rollbackOptimisticTurn(get(), sessionId, optimisticId),
        progress: get().activeSessionId === sessionId ? idleProgress : get().progress,
        progressBySession: { ...get().progressBySession, [sessionId]: idleProgress },
        lastError: toErrorMessage(error, "继续任务失败，请重试。"),
      });
    }
  },
  retryFailedMessage: async (sessionId, messageSequence, content) => {
    if (get().retryingFailureBySession[sessionId] !== undefined) return;
    const runningProgress: AssistantProgress = { status: "running", headline: "正在重试" };
    set({
      retryingFailureBySession: {
        ...get().retryingFailureBySession,
        [sessionId]: messageSequence,
      },
      progress: get().activeSessionId === sessionId ? runningProgress : get().progress,
      progressBySession: {
        ...get().progressBySession,
        [sessionId]: runningProgress,
      },
      lastError: null,
    });
    try {
      const result = await retryAssistantMessage(sessionId, messageSequence, content);
      if (!result.accepted) {
        throw new Error("重试请求未被接受。");
      }
    } catch (error) {
      const retrying = { ...get().retryingFailureBySession };
      delete retrying[sessionId];
      set({
        retryingFailureBySession: retrying,
        progress: get().activeSessionId === sessionId ? idleProgress : get().progress,
        progressBySession: {
          ...get().progressBySession,
          [sessionId]: idleProgress,
        },
        lastError: toErrorMessage(error, "重试失败，请稍后再试。"),
      });
    }
  },
  refreshSubagents: async (sessionId) => {
    try {
      const items = await listSubagents(sessionId);
      const authoritativeIds = new Set(items.map((item) => item.subagentId));
      const existingTurns = get().turnActivityBySession[sessionId] ?? {};
      // 保留实时事件已记录的排序锚点，权威恢复不应把子卡片打回末尾。
      const priorAnchors = new Map<string, number | undefined>();
      for (const turn of Object.values(existingTurns)) {
        for (const item of turn.subagents) priorAnchors.set(item.subagentId, item.anchorSeq);
      }
      const nextTurns: Record<string, AssistantTurnActivity> = {};
      for (const [turnId, turn] of Object.entries(existingTurns)) {
        nextTurns[turnId] = {
          ...turn,
          subagents: turn.subagents.filter((item) => !authoritativeIds.has(item.subagentId)),
        };
      }
      for (const item of items) {
        const targetTurnId = item.turnStartSequence
          ? turnIdFromSequence(item.turnStartSequence)
          : resolveTurnId(get(), sessionId, "session_snapshot");
        const prev = nextTurns[targetTurnId] ?? emptyTurn(targetTurnId);
        const updated: Subagent = {
          subagentId: item.subagentId,
          label: item.label,
          task: item.task,
          status: item.status,
          lastOutput: item.lastOutput ?? undefined,
          anchorSeq: priorAnchors.get(item.subagentId),
        };
        nextTurns[targetTurnId] = {
          ...prev,
          fromSequence: item.turnStartSequence ?? prev.fromSequence,
          subagents: upsertSubagent(prev.subagents, updated),
        };
      }
      set({ turnActivityBySession: { ...get().turnActivityBySession, [sessionId]: nextTurns } });
    } catch {
      set({ lastError: "无法刷新子任务状态，请重试。" });
    }
  },
  refreshActivityTranscript: async (sessionId, requestedTurnId) => {
    const turnId =
      requestedTurnId
      || get().activeTurnIdBySession[sessionId]
      || latestVisibleTurnId(sessionId, get().messages, get().pendingOptimisticMessages);
    if (!turnId) return;
    const turn = getTurn(get().turnActivityBySession, sessionId, turnId);
    try {
      const transcript = await getSubagentTranscript(sessionId, undefined, {
        afterSequence: turn.fromSequence,
        beforeSequence: turn.beforeSequence,
      });
      const steps: ActivityStep[] = transcript.steps.map((step) => ({
        seq: step.seq,
        kind: step.kind,
        toolName: step.toolName ?? undefined,
        text: step.text,
        subagentId: null,
        redacted: step.redacted ?? false,
      }));
      set({
        ...updateTurn(get(), sessionId, turnId, () => ({
          ...turn,
          turnId,
          steps,
          transcriptCompressed: transcript.compressed,
          transcriptResynced: true,
        })),
      });
    } catch {
      // transcript 兜底失败不覆盖现有实时步骤，避免把已有展示清空
      set({ lastError: "无法刷新执行过程，请重试。" });
    }
  },
  applyEvent: (event) => {
    if (event.type === "assistant.message") {
      const message: AssistantMessage = event.payload;
      const eventSessionId = event.scope.sessionId ?? "";
      if (!eventSessionId) return;
      const isActiveSession = eventSessionId === get().activeSessionId;
      const pendingEcho = get().pendingOptimisticMessages.find((pending) =>
        isPendingEcho(pending, eventSessionId, message),
      );
      const mergedMessages = isActiveSession
        ? uniqueMessages([...get().messages, message])
        : [message];
      const existingTurns = get().turnActivityBySession[eventSessionId] ?? {};
      let syncedTurns = syncTurnsFromMessages(mergedMessages, existingTurns);
      let activeTurnIdBySession = get().activeTurnIdBySession;
      if (message.role === "user") {
        const newTurnId = turnIdFromSequence(message.sequence);
        const currentActiveTurnId = get().activeTurnIdBySession[eventSessionId];
        const oldTurnId = pendingEcho?.optimisticId
          || (currentActiveTurnId?.startsWith("optimistic_") ? currentActiveTurnId : null);
        syncedTurns = migrateTurn(syncedTurns, oldTurnId, newTurnId, message.sequence);
        activeTurnIdBySession = { ...activeTurnIdBySession, [eventSessionId]: newTurnId };
      }
      const patch = {
        pendingOptimisticMessages: reconcilePendingMessages(
          get().pendingOptimisticMessages,
          eventSessionId,
          [message],
        ),
        turnActivityBySession: {
          ...get().turnActivityBySession,
          [eventSessionId]: syncedTurns,
        },
        activeTurnIdBySession,
      };
      set(isActiveSession ? { ...patch, messages: mergedMessages } : patch);
      return;
    }
    if (event.type === "assistant.progress") {
      const payload = event.payload;
      const status = (typeof payload["status"] === "string" ? payload["status"] : "running") as AssistantProgress["status"];
      const sessionId = event.scope.sessionId ?? get().activeSessionId ?? "";
      if (!sessionId) return;
      const isActiveSession = sessionId === get().activeSessionId;
      const nextProgress: AssistantProgress = {
        status,
        headline: typeof payload["headline"] === "string" ? payload["headline"] : "",
        runId: typeof payload["runId"] === "string" ? payload["runId"] : undefined,
      };
      const nextStoppingBySession = {
        ...get().stoppingBySession,
        [sessionId]: status === "running" ? Boolean(get().stoppingBySession[sessionId]) : false,
      };
      const nextRetryingFailures = { ...get().retryingFailureBySession };
      if (status !== "running") {
        delete nextRetryingFailures[sessionId];
      }
      set({
        progress: isActiveSession ? nextProgress : get().progress,
        progressBySession: { ...get().progressBySession, [sessionId]: nextProgress },
        // 离开 running（含 cancelled/succeeded/failed/waiting）即清"停止中"过渡态、解锁输入；
        // 已产内容由先到的 assistant.message 事件追加保留（FR-008）。
        stopping: isActiveSession
          ? (status === "running" ? Boolean(nextStoppingBySession[sessionId]) : false)
          : get().stopping,
        stoppingBySession: nextStoppingBySession,
        retryingFailureBySession: nextRetryingFailures,
      });
      // 排队消息：回合离开 running 时按结果处理（US2）。
      if (sessionId && status !== "running") {
        const queued = get().queuedMessageBySession[sessionId];
        if (queued) {
          const map = { ...get().queuedMessageBySession };
          delete map[sessionId];
          const autoSend =
            queued.state === "queued" && (status === "succeeded" || status === "waiting_for_user");
          if (autoSend) {
            // 已提交排队 + 成功/反问结束 → 自动派发（编辑态绝不外发，FR-015）
            const autoRunningProgress: AssistantProgress = { status: "running", headline: "正在处理" };
            const begun = beginOptimisticTurn(get(), sessionId, queued.text);
            const queuedOptimisticId = begun.optimisticId;
            // 失败时静默重排：在回滚时刻按最新状态重建，避免覆盖其它会话的并发排队改动
            const requeueText = queued.text;
            const requeueQueued = () => ({
              ...get().queuedMessageBySession,
              [sessionId]: { text: requeueText, state: "queued" as const },
            });
            set({
              queuedMessageBySession: map,
              progress: get().activeSessionId === sessionId ? autoRunningProgress : get().progress,
              progressBySession: { ...get().progressBySession, [sessionId]: autoRunningProgress },
              ...begun.patch,
            });
            void sendAssistantMessage(sessionId, queued.text)
              .then((result) => {
                if (!result.accepted) {
                  // 并发安全网：撞 accepted=false 静默重排
                  const busyProgress: AssistantProgress = { status: "running", headline: "上一条消息仍在处理中" };
                  set({
                    ...rollbackOptimisticTurn(get(), sessionId, queuedOptimisticId),
                    queuedMessageBySession: requeueQueued(),
                    progress: get().activeSessionId === sessionId ? busyProgress : get().progress,
                    progressBySession: { ...get().progressBySession, [sessionId]: busyProgress },
                  });
                } else {
                  set({
                    progress: get().activeSessionId === sessionId ? autoRunningProgress : get().progress,
                    progressBySession: { ...get().progressBySession, [sessionId]: autoRunningProgress },
                  });
                }
              })
              .catch(() => {
                set({
                  ...rollbackOptimisticTurn(get(), sessionId, queuedOptimisticId),
                  queuedMessageBySession: requeueQueued(),
                });
              });
          } else {
            // 编辑态，或 failed/cancelled 结束 → 退回普通草稿、不派发（FR-014）
            set({
              queuedMessageBySession: map,
              draft: get().activeSessionId === sessionId ? queued.text : get().draft,
              draftBySession: { ...get().draftBySession, [sessionId]: queued.text },
            });
          }
        }
      }
      return;
    }
    if (event.type === "assistant.activity") {
      const sessionId = event.scope.sessionId ?? "";
      if (!sessionId) return;
      const turnId = resolveTurnId(get(), sessionId, "live");
      const payload = event.payload as Record<string, unknown>;
      const step: ActivityStep = {
        seq: typeof payload["seq"] === "number" ? payload["seq"] : 0,
        kind: (typeof payload["kind"] === "string" ? payload["kind"] : "reasoning") as ActivityStep["kind"],
        toolName: typeof payload["toolName"] === "string" ? payload["toolName"] : undefined,
        text: typeof payload["text"] === "string" ? payload["text"] : "",
        subagentId: typeof payload["subagentId"] === "string" ? payload["subagentId"] : null,
        redacted: payload["redacted"] === true,
      };
      // 去重（按 seq）+ 升序 + 前端上限（常态顺序追加免排序）
      set(
        commitLiveTurn(get(), sessionId, turnId, (turn) => ({
          ...turn,
          steps: appendActivityStep(turn.steps, step, MAX_LIVE_ACTIVITY_STEPS),
        })),
      );
      return;
    }
    if (event.type === "assistant.subagent") {
      const sessionId = event.scope.sessionId ?? "";
      if (!sessionId) return;
      const turnId = resolveTurnId(get(), sessionId, "live");
      const payload = event.payload as Record<string, unknown>;
      const subagentId = typeof payload["subagentId"] === "string" ? payload["subagentId"] : "";
      if (!subagentId) return;
      set(
        commitLiveTurn(get(), sessionId, turnId, (turn) => {
          const prev = turn.subagents.find((item) => item.subagentId === subagentId);
          // 首次出现时锚定到主时间线末尾步骤的 seq（委派位置）；后续更新保留首次锚点，避免被往后推。
          const lastStep = turn.steps[turn.steps.length - 1];
          const anchorSeq = prev?.anchorSeq ?? lastStep?.seq;
          const updated: Subagent = {
            subagentId,
            label: typeof payload["label"] === "string" ? payload["label"] : prev?.label ?? "子助手",
            task: typeof payload["task"] === "string" ? payload["task"] : prev?.task ?? "",
            status: (typeof payload["status"] === "string" ? payload["status"] : prev?.status ?? "running") as Subagent["status"],
            lastOutput: typeof payload["lastOutput"] === "string" ? payload["lastOutput"] : prev?.lastOutput,
            anchorSeq,
          };
          return { ...turn, subagents: upsertSubagent(turn.subagents, updated) };
        }),
      );
      return;
    }
    if (event.type === "backend.resync_required") {
      // 缺口/会话不匹配：以权威端点刷新子任务列表与当前回合过程（FR-032），不凭内部事件名猜测
      const sessionId = get().activeSessionId;
      if (sessionId) {
        void get().selectSession(sessionId);
        void get().refreshSubagents(sessionId);
        void get().refreshActivityTranscript(sessionId);
      }
      return;
    }
    if (event.type === "assistant.error") {
      const payload = event.payload;
      const message = typeof payload["message"] === "string" ? payload["message"] : "Assistant 处理失败";
      const sessionId = event.scope.sessionId ?? "";
      const failedProgress: AssistantProgress = { status: "failed", headline: message };
      set({
        progress: sessionId && sessionId !== get().activeSessionId ? get().progress : failedProgress,
        progressBySession: sessionId
          ? { ...get().progressBySession, [sessionId]: failedProgress }
          : get().progressBySession,
        lastError: sessionId && sessionId !== get().activeSessionId ? get().lastError : message,
      });
      return;
    }
    if (event.type === "assistant.confirmation") {
      const confirmation: AssistantConfirmation = event.payload;
      if (confirmation.sessionId && confirmation.sessionId !== get().activeSessionId) {
        if (
          confirmation.actionType !== "skill.edit_protected"
          && confirmation.actionType !== "skill.soft_delete"
        ) {
          return;
        }
      }
      set({
        confirmations: [
          ...get().confirmations.filter((item) => item.requestId !== confirmation.requestId),
          confirmation,
        ],
      });
    }
  },
  decideConfirmation: async (requestId, decision) => {
    try {
      await decideAssistantConfirmation(requestId, decision);
      set({
        confirmations: get().confirmations.filter((confirmation) => confirmation.requestId !== requestId),
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "操作确认失败。") });
    }
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
