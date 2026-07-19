import { create } from "zustand";

import {
  deleteScheduledTask,
  fireScheduledTaskNow,
  getScheduledTask,
  listPendingSchedulingConfirmations,
  listScheduledTaskRuns,
  listScheduledTasks,
  patchScheduledTask,
  submitSchedulingConfirmationDecision,
  takeoverScheduledRun,
} from "../api/scheduledTasks";
import type {
  PendingSchedulingConfirmation,
  ScheduledTaskItem,
  ScheduledTaskPatchInput,
  ScheduledTaskRunItem,
  SchedulingConfirmationDecisionInput,
  SchedulingConfirmationDraft,
  TakeoverResponse,
} from "../api/scheduledTasks";
import type { UiEvent } from "../api/client";
import { sendDesktopNotification } from "../utils/desktopNotification";
import { createDebouncedRefresh, toErrorMessage } from "./helpers";
import { useToastStore } from "./toastStore";

// 复制删除：scheduled_task.changed 收到 changeType=deleted 时本地立刻移除行。
function withoutTask(items: ScheduledTaskItem[], taskId: string): ScheduledTaskItem[] {
  return items.filter((item) => item.scheduledTaskId !== taskId);
}

// 从 record 里按 key 删除并返回新 record（不可变）。eslint 友好的丢弃模式。
function dropKey<T extends Record<string, unknown>>(record: T, key: string): T {
  if (!(key in record)) return record;
  const next: Record<string, unknown> = { ...record };
  delete next[key];
  return next as T;
}

function replaceTask(items: ScheduledTaskItem[], next: ScheduledTaskItem): ScheduledTaskItem[] {
  const idx = items.findIndex((item) => item.scheduledTaskId === next.scheduledTaskId);
  if (idx < 0) return [next, ...items];
  const copy = items.slice();
  copy[idx] = next;
  return copy;
}

const scheduleListRefresh = createDebouncedRefresh(300);

export interface ScheduledState {
  hydrated: boolean;
  tasks: ScheduledTaskItem[];
  tasksTotal: number;
  taskDetail: ScheduledTaskItem | null;
  runsByTask: Record<string, ScheduledTaskRunItem[]>;
  runsTotalByTask: Record<string, number>;
  expandedTaskIds: Set<string>;
  pendingConfirmation: PendingSchedulingConfirmation | null;
  submittingConfirmation: boolean;
  loading: boolean;
  loadingDetail: boolean;
  loadingRunsTaskIds: string[];
  lastError: string | null;
  needsResync: boolean;

  load: () => Promise<void>;
  loadDetail: (taskId: string) => Promise<void>;
  loadRuns: (taskId: string) => Promise<void>;
  toggleExpanded: (taskId: string, next?: boolean) => void;
  patchTask: (taskId: string, patch: ScheduledTaskPatchInput) => Promise<ScheduledTaskItem | null>;
  fireNow: (taskId: string) => Promise<boolean>;
  remove: (taskId: string) => Promise<boolean>;
  takeover: (taskId: string, runId: string) => Promise<TakeoverResponse | null>;
  submitConfirmation: (
    requestId: string,
    decision: SchedulingConfirmationDecisionInput["decision"],
    editedDraft?: SchedulingConfirmationDraft,
    unattendedAutoApprove?: boolean,
  ) => Promise<void>;
  cancelConfirmation: (requestId: string) => Promise<void>;
  refreshPendingConfirmation: () => Promise<void>;
  clearPendingConfirmation: () => void;
  applyEvent: (event: UiEvent) => void;
  markNeedsResync: () => void;
  setError: (message: string | null) => void;
  reset: () => void;
}

type RemovedTaskState = Pick<
  ScheduledState,
  | "tasks"
  | "tasksTotal"
  | "taskDetail"
  | "runsByTask"
  | "runsTotalByTask"
  | "expandedTaskIds"
  | "loadingRunsTaskIds"
>;

function removeTaskFromState(state: ScheduledState, taskId: string): RemovedTaskState {
  const existed = state.tasks.some((task) => task.scheduledTaskId === taskId);
  const expanded = new Set(state.expandedTaskIds);
  expanded.delete(taskId);
  return {
    tasks: withoutTask(state.tasks, taskId),
    tasksTotal: existed ? Math.max(0, state.tasksTotal - 1) : state.tasksTotal,
    taskDetail:
      state.taskDetail?.scheduledTaskId === taskId ? null : state.taskDetail,
    runsByTask: dropKey(state.runsByTask, taskId),
    runsTotalByTask: dropKey(state.runsTotalByTask, taskId),
    expandedTaskIds: expanded,
    loadingRunsTaskIds: state.loadingRunsTaskIds.filter((id) => id !== taskId),
  };
}

export const useScheduledStore = create<ScheduledState>((set, get) => ({
  hydrated: false,
  tasks: [],
  tasksTotal: 0,
  taskDetail: null,
  runsByTask: {},
  runsTotalByTask: {},
  expandedTaskIds: new Set<string>(),
  pendingConfirmation: null,
  submittingConfirmation: false,
  loading: false,
  loadingDetail: false,
  loadingRunsTaskIds: [],
  lastError: null,
  needsResync: false,
  setError: (message) => set({ lastError: message }),
  markNeedsResync: () => set({ needsResync: true }),
  reset: () =>
    set({
      hydrated: false,
      tasks: [],
      tasksTotal: 0,
      taskDetail: null,
      runsByTask: {},
      runsTotalByTask: {},
      expandedTaskIds: new Set<string>(),
      pendingConfirmation: null,
      submittingConfirmation: false,
      loading: false,
      loadingDetail: false,
      loadingRunsTaskIds: [],
      lastError: null,
      needsResync: false,
    }),
  load: async () => {
    set({ loading: true, lastError: null });
    try {
      const response = await listScheduledTasks({ limit: 200, offset: 0 });
      set({
        hydrated: true,
        tasks: response.items,
        tasksTotal: response.total,
        needsResync: false,
      });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载定时任务列表。"), needsResync: true });
      throw error;
    } finally {
      set({ loading: false });
    }
  },
  loadDetail: async (taskId) => {
    set({ loadingDetail: true, lastError: null });
    try {
      const detail = await getScheduledTask(taskId);
      set({ taskDetail: detail, needsResync: false });
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法加载任务详情。") });
    } finally {
      set({ loadingDetail: false });
    }
  },
  loadRuns: async (taskId) => {
    set((state) => ({
      loadingRunsTaskIds: state.loadingRunsTaskIds.includes(taskId)
        ? state.loadingRunsTaskIds
        : [...state.loadingRunsTaskIds, taskId],
    }));
    try {
      const response = await listScheduledTaskRuns(taskId, { limit: 50, offset: 0 });
      set((state) => ({
        runsByTask: { ...state.runsByTask, [taskId]: response.items },
        runsTotalByTask: { ...state.runsTotalByTask, [taskId]: response.total },
        loadingRunsTaskIds: state.loadingRunsTaskIds.filter((id) => id !== taskId),
      }));
    } catch (error) {
      set((state) => ({
        lastError: toErrorMessage(error, "无法加载执行记录。"),
        loadingRunsTaskIds: state.loadingRunsTaskIds.filter((id) => id !== taskId),
      }));
    }
  },
  toggleExpanded: (taskId, next) => {
    set((state) => {
      const expanded = new Set(state.expandedTaskIds);
      const target = next === undefined ? !expanded.has(taskId) : next;
      if (target) expanded.add(taskId);
      else expanded.delete(taskId);
      return { expandedTaskIds: expanded };
    });
  },
  patchTask: async (taskId, patch) => {
    try {
      const updated = await patchScheduledTask(taskId, patch);
      set((state) => ({
        tasks: replaceTask(state.tasks, updated),
        taskDetail:
          state.taskDetail && state.taskDetail.scheduledTaskId === taskId ? updated : state.taskDetail,
        needsResync: false,
      }));
      return updated;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法更新任务设置。") });
      return null;
    }
  },
  fireNow: async (taskId) => {
    try {
      await fireScheduledTaskNow(taskId);
      // 触发后会经 scheduled_task.changed 事件刷新列表；乐观地也刷一次。
      scheduleListRefresh(() => get().load().catch(() => undefined));
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法立即触发任务。") });
      return false;
    }
  },
  remove: async (taskId) => {
    try {
      await deleteScheduledTask(taskId);
      set((state) => removeTaskFromState(state, taskId));
      return true;
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法删除任务。") });
      return false;
    }
  },
  takeover: async (taskId, runId) => {
    try {
      return await takeoverScheduledRun(taskId, runId);
    } catch (error) {
      set({ lastError: toErrorMessage(error, "无法接管这个执行记录。") });
      return null;
    }
  },
  submitConfirmation: async (requestId, decision, editedDraft, unattendedAutoApprove) => {
    const pending = get().pendingConfirmation;
    if (!pending || pending.requestId !== requestId) {
      return;
    }
    set({ submittingConfirmation: true, lastError: null });
    try {
      const input: SchedulingConfirmationDecisionInput = {
        decision,
        ...(editedDraft ? { editedDraft } : {}),
        ...(typeof unattendedAutoApprove === "boolean" ? { unattendedAutoApprove } : {}),
      };
      const created = await submitSchedulingConfirmationDecision(requestId, input);
      // 成功：先清 pending；created 任务由 scheduled_task.changed 事件落入列表。
      // 若 created 已返回（confirm 路径），乐观插入以便用户立刻看见。
      let resolvedCurrent = false;
      set((state) => {
        // 请求在途时可能收到另一张 confirmation_requested；旧请求的迟到响应
        // 绝不能把新卡清掉，也不能解除新卡自己的 submitting 门控。
        resolvedCurrent = state.pendingConfirmation?.requestId === requestId;
        return {
          pendingConfirmation: resolvedCurrent ? null : state.pendingConfirmation,
          submittingConfirmation: resolvedCurrent
            ? false
            : state.submittingConfirmation,
          tasks:
            created && decision === "confirm"
              ? replaceTask(state.tasks, created)
              : state.tasks,
        };
      });
      if (resolvedCurrent) {
        void get()
          .refreshPendingConfirmation()
          .catch(() => undefined);
      }
    } catch (error) {
      set((state) =>
        state.pendingConfirmation?.requestId === requestId
          ? {
              submittingConfirmation: false,
              lastError: toErrorMessage(error, "无法提交确认决策，请稍后重试。"),
            }
          : {},
      );
    }
  },
  cancelConfirmation: async (requestId) => {
    const pending = get().pendingConfirmation;
    if (!pending || pending.requestId !== requestId) {
      return;
    }
    set({ submittingConfirmation: true, lastError: null });
    try {
      await submitSchedulingConfirmationDecision(requestId, { decision: "cancel" });
      let resolvedCurrent = false;
      set((state) => {
        resolvedCurrent = state.pendingConfirmation?.requestId === requestId;
        return {
          pendingConfirmation: resolvedCurrent ? null : state.pendingConfirmation,
          submittingConfirmation: resolvedCurrent
            ? false
            : state.submittingConfirmation,
        };
      });
      if (resolvedCurrent) {
        void get()
          .refreshPendingConfirmation()
          .catch(() => undefined);
      }
    } catch (error) {
      set((state) =>
        state.pendingConfirmation?.requestId === requestId
          ? {
              submittingConfirmation: false,
              lastError: toErrorMessage(error, "取消失败，请稍后重试。"),
            }
          : {},
      );
    }
  },
  refreshPendingConfirmation: async () => {
    try {
      const response = await listPendingSchedulingConfirmations();
      // 取第一条 pending（同一时刻最多展示一张确认卡，对齐 019 单 active 风格）。
      const next = response.items[0] ?? null;
      set({ pendingConfirmation: next });
    } catch (error) {
      set({
        lastError: toErrorMessage(error, "无法恢复待确认任务，请检查连接后重试。"),
        needsResync: true,
      });
      throw error;
    }
  },
  clearPendingConfirmation: () => set({ pendingConfirmation: null, submittingConfirmation: false }),
  applyEvent: (event) => {
    if (event.type === "backend.resync_required") {
      const domains = Array.isArray(event.payload.domains) ? event.payload.domains : [];
      if (domains.includes("scheduled") || domains.includes("scheduling") || domains.length === 0) {
        set({ needsResync: true });
      }
      return;
    }
    if (event.type === "scheduled_task.changed") {
      const taskId = String(event.payload.taskId ?? "");
      const changeType = String(event.payload.changeType ?? "");
      if (!taskId) {
        set({ needsResync: true });
        return;
      }
      if (changeType === "deleted") {
        set((state) => removeTaskFromState(state, taskId));
        return;
      }
      // 其他变更类型（created/paused/resumed/fired/status_changed）：列表层字段需要权威刷新。
      scheduleListRefresh(() => get().load().catch(() => undefined));
      return;
    }
    if (event.type === "scheduled_task.completed") {
      const outcome = String(event.payload.outcome ?? "");
      const taskTitle = typeof event.payload.taskTitle === "string" ? event.payload.taskTitle : "定时任务";
      const summary = typeof event.payload.summary === "string" ? event.payload.summary : null;
      const failureReason =
        typeof event.payload.failureReason === "string" ? event.payload.failureReason : null;
      // completed 事件权威承载任务终态：列表层 last_run_outcome/last_run_at 必须刷新。
      scheduleListRefresh(() => get().load().catch(() => undefined));
      if (outcome === "succeeded") {
        const message = summary ? `${taskTitle} 已完成：${summary}` : `${taskTitle} 已完成`;
        useToastStore.getState().notifySuccess(message);
        void sendDesktopNotification({ title: "定时任务已完成", body: taskTitle });
      } else if (outcome === "failed") {
        const message = failureReason
          ? `${taskTitle} 没跑成功：${failureReason}`
          : `${taskTitle} 没跑成功`;
        useToastStore.getState().notifyWarning(message);
        void sendDesktopNotification({ title: "定时任务未成功", body: taskTitle });
      }
      return;
    }
    if (event.type === "scheduled_task.needs_takeover") {
      const reason = String(event.payload.reason ?? "");
      const taskTitle = typeof event.payload.taskTitle === "string" ? event.payload.taskTitle : "定时任务";
      // run 落 waiting_user / failed_takeover：历史层需要刷新。
      scheduleListRefresh(() => get().load().catch(() => undefined));
      const message =
        reason === "failed_takeover"
          ? `${taskTitle} 跑了一半失败了，要不要接着处理一下？`
          : `${taskTitle} 需要你的帮助才能继续`;
      useToastStore.getState().notifyWarning(message);
      void sendDesktopNotification({ title: "定时任务需要你的帮助", body: taskTitle });
      return;
    }
    if (event.type === "scheduling.confirmation_requested") {
      // payload 已由 parseUiEvent 校验：requestId/sessionId/draft/expiresAt 必填。
      // 同一时刻最多展示一张确认卡：以最新事件为准（first-decision-wins 由后端裁定）。
      set({
        pendingConfirmation: {
          requestId: event.payload.requestId,
          sessionId: event.payload.sessionId,
          draft: event.payload.draft,
          unattendedAutoApprove:
            typeof event.payload.unattendedAutoApprove === "boolean"
              ? event.payload.unattendedAutoApprove
              : false,
          expiresAt: event.payload.expiresAt,
          status: "pending",
        },
        submittingConfirmation: false,
      });
      return;
    }
    if (event.type === "scheduling.confirmation_resolved") {
      // 只清除同 requestId 的卡。多会话可能同时产生 pending；旧卡的迟到 resolved
      // 不能误关当前正在展示的新卡。随后拉权威快照，顺序展示仍待处理的下一张。
      const requestId = String(event.payload.requestId ?? "");
      let clearedCurrent = false;
      set((state) => {
        if (!requestId || state.pendingConfirmation?.requestId !== requestId) {
          return {};
        }
        clearedCurrent = true;
        return { pendingConfirmation: null, submittingConfirmation: false };
      });
      if (clearedCurrent) {
        void get()
          .refreshPendingConfirmation()
          .catch(() => undefined);
      }
      return;
    }
  },
}));

export type { ScheduledTaskItem, ScheduledTaskRunItem, PendingSchedulingConfirmation };
