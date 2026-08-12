import { create } from "zustand";

import {
  createAssistantSession,
  decideAssistantConfirmation,
  deleteAssistantSession,
  getPendingClarification,
  getSubagentTranscript,
  listAssistantMessages,
  listAssistantSessions,
  listSubagents,
  renameAssistantSession,
  retryAssistantMessage,
  sendAssistantMessage,
  setAssistantAutoApprove,
  stopAssistantRun,
  submitClarificationDecision,
  triggerAssistantSegmentBoundary,
  triggerAssistantSegmentIdle,
} from "../api/assistant";
import type {
  AssistantConfirmation,
  AssistantMessage,
  AssistantSession,
  ClarificationAnswerInput,
  ClarificationRequest,
} from "../api/assistant";
import type { UiEvent } from "../api/client";
import { toErrorMessage } from "./helpers";

import { applyAssistantEvent } from "./assistantEventHandlers";
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
  beginOptimisticTurn,
  emptyTurn,
  getTurn,
  latestVisibleTurnId,
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
export { emptyTurn, turnIdFromMessage, turnIdFromSequence } from "./assistantHelpers";

// 单题未提交草稿（019 结构化多选澄清）
export type ClarificationQuestionDraft = {
  optionIds: string[];
  // "其他"是否被选中——区分"选了其他但还没填"与"没选其他"
  otherSelected: boolean;
  otherText: string;
};

async function sealPreviousSegment(prevSessionId: string | null): Promise<void> {
  if (prevSessionId) {
    try { await triggerAssistantSegmentBoundary(prevSessionId, "new_session"); } catch { /* best-effort */ }
  }
}

// 清理某会话的澄清状态（pending + 草稿 + 提交态）。resolved 事件、提交/取消成功、快照为空时调用。
function clearClarificationForSession(
  set: (partial: Partial<AssistantState>) => void,
  get: () => AssistantState,
  sessionId: string,
): void {
  const pending = { ...get().pendingClarificationBySession };
  const drafts = { ...get().clarificationDraftsBySession };
  const submitting = { ...get().clarificationSubmittingBySession };
  delete pending[sessionId];
  delete drafts[sessionId];
  delete submitting[sessionId];
  set({
    pendingClarificationBySession: pending,
    clarificationDraftsBySession: drafts,
    clarificationSubmittingBySession: submitting,
  });
}

let _idleTimerRef: ReturnType<typeof setTimeout> | null = null;

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
  // === 019 结构化多选澄清（按 session，内存态，与高危确认完全分离）===
  // 当前会话待答澄清；切换会话保留草稿，resolved 后清理。
  pendingClarificationBySession: Record<string, ClarificationRequest>;
  // 未提交草稿：sessionId → questionId → { optionIds, otherText }
  clarificationDraftsBySession: Record<string, Record<string, ClarificationQuestionDraft>>;
  clarificationSubmittingBySession: Record<string, boolean>;
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
  // 澄清草稿/提交/取消/快照刷新（019）
  setClarificationDraft: (
    sessionId: string,
    questionId: string,
    draft: ClarificationQuestionDraft,
  ) => void;
  submitClarification: (sessionId: string) => Promise<void>;
  cancelClarification: (sessionId: string) => Promise<void>;
  refreshPendingClarification: (sessionId: string) => Promise<void>;
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
  pendingClarificationBySession: {},
  clarificationDraftsBySession: {},
  clarificationSubmittingBySession: {},
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
      // 待答澄清快照兜底（重开/重连恢复卡片，019 FR-014）
      void get().refreshPendingClarification(sessionId);
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
          taskId: item.taskId ?? null,
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
  applyEvent: (event) => applyAssistantEvent(event, { set, get, clearClarificationForSession }),
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
  setClarificationDraft: (sessionId, questionId, draft) => {
    const bySession = get().clarificationDraftsBySession;
    set({
      clarificationDraftsBySession: {
        ...bySession,
        [sessionId]: { ...(bySession[sessionId] ?? {}), [questionId]: draft },
      },
    });
  },
  submitClarification: async (sessionId) => {
    const pending = get().pendingClarificationBySession[sessionId];
    if (!pending) {
      return;
    }
    const drafts = get().clarificationDraftsBySession[sessionId] ?? {};
    const answers: ClarificationAnswerInput[] = pending.questions.map((q) => {
      const d = drafts[q.questionId] ?? { optionIds: [], otherSelected: false, otherText: "" };
      const otherText = d.otherSelected ? d.otherText.trim() : "";
      return {
        questionId: q.questionId,
        selectedOptionIds: d.optionIds,
        otherText: otherText ? otherText : null,
      };
    });
    set({
      clarificationSubmittingBySession: {
        ...get().clarificationSubmittingBySession,
        [sessionId]: true,
      },
    });
    try {
      await submitClarificationDecision(sessionId, pending.requestId, { decision: "submit", answers });
      // 成功：以 resolved 事件为权威清理；这里同步清理兜底（事件可能先到也可能后到）
      clearClarificationForSession(set, get, sessionId);
    } catch (error) {
      set({
        clarificationSubmittingBySession: {
          ...get().clarificationSubmittingBySession,
          [sessionId]: false,
        },
        lastError: toErrorMessage(error, "提交回答失败，请检查每题是否已作答。"),
      });
    }
  },
  cancelClarification: async (sessionId) => {
    const pending = get().pendingClarificationBySession[sessionId];
    if (!pending) {
      return;
    }
    set({
      clarificationSubmittingBySession: {
        ...get().clarificationSubmittingBySession,
        [sessionId]: true,
      },
    });
    try {
      await submitClarificationDecision(sessionId, pending.requestId, { decision: "cancel", answers: [] });
      clearClarificationForSession(set, get, sessionId);
    } catch (error) {
      set({
        clarificationSubmittingBySession: {
          ...get().clarificationSubmittingBySession,
          [sessionId]: false,
        },
        lastError: toErrorMessage(error, "取消失败，请稍后重试。"),
      });
    }
  },
  refreshPendingClarification: async (sessionId) => {
    if (!sessionId) {
      return;
    }
    try {
      const pending = await getPendingClarification(sessionId);
      if (pending) {
        set({
          pendingClarificationBySession: {
            ...get().pendingClarificationBySession,
            [sessionId]: pending,
          },
        });
      } else {
        clearClarificationForSession(set, get, sessionId);
      }
    } catch {
      /* best-effort 快照刷新，失败保留现状 */
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
