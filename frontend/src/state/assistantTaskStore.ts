import { create } from "zustand";

import {
  continueAssistantTaskGraph,
  decideAssistantTaskAdjudication,
  getAssistantTaskGraph,
  getAssistantMeetingTranscript,
  getAssistantTaskBoard,
  getAssistantTaskTodos,
  getCurrentAssistantTaskGraph,
  stopAssistantTaskGraph,
  updateAssistantTaskTodos,
} from "../api/assistantTasks";
import { useExternalCodingSessionStore } from "./externalCodingSessionStore";
import type { TaskAdjudicationDecision } from "../api/assistantTasks";
import type {
  AssistantMeetingTranscript,
  AssistantTaskBoardItem,
  AssistantTaskGraphSnapshot,
  AssistantTodoItem,
} from "../api/assistantTasks";
import type { UiEvent } from "../api/client";
import { toErrorMessage } from "./helpers";

interface AssistantTaskState {
  currentGraph: AssistantTaskGraphSnapshot | null;
  boardItems: AssistantTaskBoardItem[];
  activeMeeting: AssistantMeetingTranscript | null;
  todosByTaskId: Record<string, AssistantTodoItem[]>;
  todoLoadingTaskIds: string[];
  loadedTodoTaskIds: Set<string>;
  loadedTodoGraphKey: string;
  graphLoading: boolean;
  boardLoading: boolean;
  meetingLoading: boolean;
  graphError: string | null;
  boardError: string | null;
  meetingError: string | null;
  needsResync: boolean;
  /** user_task.changed 事件到达时递增，供 AssistantScreen 触发用户任务列表刷新。 */
  userTaskVersion: number;
  loadCurrentGraph: (sessionId: string) => Promise<void>;
  reloadGraph: (sessionId: string, graphId: string) => Promise<void>;
  loadBoard: (sessionId: string) => Promise<void>;
  loadMeeting: (sessionId: string, channelId: string) => Promise<void>;
  loadTodos: (sessionId: string, taskId: string) => Promise<void>;
  updateTodos: (
    sessionId: string,
    taskId: string,
    executorType: "ephemeral_subagent" | "specialist",
    executorId: string,
    items: AssistantTodoItem[],
  ) => Promise<void>;
  stopGraph: (sessionId: string, graphId: string, runId?: string | null) => Promise<void>;
  continueGraph: (sessionId: string, graphId: string) => Promise<void>;
  decideAdjudication: (
    sessionId: string,
    adjudicationId: string,
    decision: TaskAdjudicationDecision,
    instruction?: string,
  ) => Promise<void>;
  applyEvent: (event: UiEvent) => void;
  closeMeeting: () => void;
  setCurrentGraph: (graph: AssistantTaskGraphSnapshot | null) => void;
  markNeedsResync: () => void;
  loadNewTaskTodos: (sessionId: string, currentTaskIds: string[], currentTaskIdsKey: string) => void;
  executeResync: (
    sessionId: string,
    activeMeetingChannelId: string | null,
    currentTaskIds: string[],
  ) => Promise<void>;
  clearSessionTracking: () => void;
  reset: () => void;
}

function orderedTodos(items: AssistantTodoItem[]): AssistantTodoItem[] {
  return [...items].sort((left, right) => left.sortOrder - right.sortOrder);
}

// 图级变更（无 taskId 但图结构已变）：必须 resync 拉权威快照。
const GRAPH_LEVEL_CHANGE_TYPES = new Set([
  "graph_created",
  "graph_completed",
  "graph_stopped",
  "graph_cancelled",
  "root_failed",
  "graph_continued",
]);

type AssistantTaskSet = (
  partial:
    | Partial<AssistantTaskState>
    | ((state: AssistantTaskState) => Partial<AssistantTaskState>),
) => void;

async function runGraphMutation(
  set: AssistantTaskSet,
  sessionId: string,
  graphId: string,
  apiCall: () => Promise<unknown>,
  fallback: string,
): Promise<void> {
  set({ graphLoading: true, graphError: null });
  try {
    await apiCall();
    const graph = await getAssistantTaskGraph(sessionId, graphId);
    set({ currentGraph: graph, graphLoading: false, needsResync: false });
  } catch (error) {
    set({ graphError: toErrorMessage(error, fallback), graphLoading: false });
  }
}

async function runBoardMutation(
  set: AssistantTaskSet,
  sessionId: string,
  apiCall: () => Promise<unknown>,
  fallback: string,
): Promise<void> {
  set({ boardLoading: true, boardError: null });
  try {
    await apiCall();
    const response = await getAssistantTaskBoard(sessionId);
    set({ boardItems: response.items, boardLoading: false, needsResync: false });
  } catch (error) {
    set({ boardError: toErrorMessage(error, fallback), boardLoading: false, needsResync: true });
  }
}

function addTodoLoadingId(ids: string[], taskId: string): string[] {
  return ids.includes(taskId) ? ids : [...ids, taskId];
}

function removeTodoLoadingId(ids: string[], taskId: string): string[] {
  return ids.filter((id) => id !== taskId);
}

export const useAssistantTaskStore = create<AssistantTaskState>((set, get) => ({
  currentGraph: null,
  boardItems: [],
  activeMeeting: null,
  todosByTaskId: {},
  todoLoadingTaskIds: [],
  loadedTodoTaskIds: new Set<string>(),
  loadedTodoGraphKey: "",
  graphLoading: false,
  boardLoading: false,
  meetingLoading: false,
  graphError: null,
  boardError: null,
  meetingError: null,
  needsResync: false,
  userTaskVersion: 0,
  loadCurrentGraph: async (sessionId) => {
    set({ graphLoading: true, graphError: null });
    try {
      const response = await getCurrentAssistantTaskGraph(sessionId);
      set({ currentGraph: response.graph, graphLoading: false, needsResync: false });
    } catch (error) {
      set({ graphError: toErrorMessage(error, "任务进度加载失败"), graphLoading: false, needsResync: true });
    }
  },
  reloadGraph: async (sessionId, graphId) => {
    await runGraphMutation(set, sessionId, graphId, async () => {}, "任务进度刷新失败");
  },
  loadBoard: async (sessionId) => {
    await runBoardMutation(set, sessionId, async () => {}, "任务看板加载失败");
  },
  loadMeeting: async (sessionId, channelId) => {
    set({ meetingLoading: true, meetingError: null });
    try {
      const activeMeeting = await getAssistantMeetingTranscript(sessionId, channelId);
      set({ activeMeeting, meetingLoading: false, needsResync: false });
    } catch (error) {
      set({
        meetingError: toErrorMessage(error, "会议记录加载失败"),
        meetingLoading: false,
        needsResync: true,
      });
    }
  },
  loadTodos: async (sessionId, taskId) => {
    set((state) => ({ todoLoadingTaskIds: addTodoLoadingId(state.todoLoadingTaskIds, taskId) }));
    try {
      const response = await getAssistantTaskTodos(sessionId, taskId);
      set((state) => {
        const nextLoaded = new Set(state.loadedTodoTaskIds);
        nextLoaded.add(taskId);
        return {
          todosByTaskId: {
            ...state.todosByTaskId,
            [taskId]: orderedTodos(response.items),
          },
          todoLoadingTaskIds: removeTodoLoadingId(state.todoLoadingTaskIds, taskId),
          loadedTodoTaskIds: nextLoaded,
          needsResync: false,
        };
      });
    } catch {
      set((state) => ({
        todoLoadingTaskIds: removeTodoLoadingId(state.todoLoadingTaskIds, taskId),
        needsResync: true,
      }));
    }
  },
  updateTodos: async (sessionId, taskId, executorType, executorId, items) => {
    const previous = get().todosByTaskId[taskId] ?? [];
    set((state) => ({
      todosByTaskId: {
        ...state.todosByTaskId,
        [taskId]: orderedTodos(items),
      },
      todoLoadingTaskIds: addTodoLoadingId(state.todoLoadingTaskIds, taskId),
    }));
    try {
      const response = await updateAssistantTaskTodos(
        sessionId,
        taskId,
        executorType,
        executorId,
        items,
      );
      set((state) => ({
        todosByTaskId: {
          ...state.todosByTaskId,
          [taskId]: orderedTodos(response.items),
        },
        todoLoadingTaskIds: removeTodoLoadingId(state.todoLoadingTaskIds, taskId),
        needsResync: false,
      }));
    } catch {
      set((state) => ({
        todosByTaskId: {
          ...state.todosByTaskId,
          [taskId]: previous,
        },
        todoLoadingTaskIds: removeTodoLoadingId(state.todoLoadingTaskIds, taskId),
        // 闭包 previous 是 API 调用前的快照；in-flight 期间到达的 todo.changed 事件
        // 更新会被这次整盘回滚覆盖。标记 resync 让前端重新拉权威快照，不静默丢更新。
        needsResync: true,
      }));
    }
  },
  stopGraph: async (sessionId, graphId, runId = null) => {
    await runGraphMutation(
      set,
      sessionId,
      graphId,
      () => stopAssistantTaskGraph(sessionId, graphId, runId),
      "任务停止失败",
    );
  },
  continueGraph: async (sessionId, graphId) => {
    await runGraphMutation(
      set,
      sessionId,
      graphId,
      () => continueAssistantTaskGraph(sessionId, graphId),
      "任务继续失败",
    );
  },
  decideAdjudication: async (sessionId, adjudicationId, decision, instruction = "") => {
    set({ graphLoading: true, graphError: null });
    try {
      const result = await decideAssistantTaskAdjudication(
        sessionId,
        adjudicationId,
        decision,
        instruction,
      );
      const graph = await getAssistantTaskGraph(sessionId, result.graphId);
      set({ currentGraph: graph, graphLoading: false, needsResync: false });
    } catch (error) {
      set({ graphError: toErrorMessage(error, "任务裁定失败"), graphLoading: false });
    }
  },
  applyEvent: (event) => {
    if (event.type === "backend.resync_required") {
      const domains = Array.isArray(event.payload.domains) ? event.payload.domains : [];
      if (
        domains.includes("assistant_tasks") ||
        domains.includes("assistant_task_board") ||
        domains.includes("assistant_meetings") ||
        domains.includes("assistant_todos")
      ) {
        set({ needsResync: true });
      }
      return;
    }
    if (event.type === "assistant.task_question.changed") {
      // question 事件仅标记 resync——具体问答状态由 assistant 消息流呈现，
      // 不在 task store 内维护独立问答列表。
      set({ needsResync: true });
      return;
    }
    if (event.type === "assistant.task_board.changed") {
      set((state) => {
        const taskId = String(event.payload.taskId ?? "");
        if (!taskId) return state;
        const existing = state.boardItems.some((item) => item.taskId === taskId);
        if (!existing || event.payload.changeType === "completed") {
          return { needsResync: true };
        }
        return {
          boardItems: state.boardItems.map((item) =>
            item.taskId === taskId
              ? {
                  ...item,
                  claimStatus:
                    event.payload.claimStatus === "claimed"
                      ? "claimed"
                      : event.payload.claimStatus === "open" ||
                          event.payload.changeType === "released" ||
                          event.payload.changeType === "expired" ||
                          event.payload.changeType === "rejected"
                        ? "open"
                        : item.claimStatus,
                  updatedAt:
                    typeof event.payload.updatedAt === "string"
                      ? event.payload.updatedAt
                      : item.updatedAt,
                }
              : item,
          ),
        };
      });
      return;
    }
    if (event.type === "assistant.meeting.changed") {
      // Meeting channel ID is tracked in activeMeeting?.channelId.
      // Only mark resync so the consumer reloads the authoritative transcript.
      set({ needsResync: true });
      return;
    }
    if (event.type === "assistant.todo.changed") {
      // created/deleted/reordered 改变集合结构或批量顺序，单条局部更新无法表达；
      // 按 CLAUDE.md「assistant.todo.changed 只做局部提示，缺口必须 resync」拉权威快照。
      if (String(event.payload.changeType ?? "") !== "updated") {
        set({ needsResync: true });
        return;
      }
      set((state) => {
        const taskId = String(event.payload.taskId ?? "");
        const todoId = String(event.payload.todoId ?? "");
        if (!taskId || !todoId) return state;
        const current = state.todosByTaskId[taskId];
        if (!current) {
          return { needsResync: true };
        }
        const existingIndex = current.findIndex((item) => item.todoId === todoId);
        if (existingIndex < 0) {
          return { needsResync: true };
        }
        const next = current.map((item, index) =>
          index === existingIndex
            ? {
                ...item,
                status:
                  event.payload.status === "todo" ||
                  event.payload.status === "doing" ||
                  event.payload.status === "done" ||
                  event.payload.status === "skipped"
                    ? event.payload.status
                    : item.status,
                sortOrder:
                  typeof event.payload.sortOrder === "number"
                    ? event.payload.sortOrder
                    : item.sortOrder,
              }
            : item,
        );
        return {
          todosByTaskId: {
            ...state.todosByTaskId,
            [taskId]: orderedTodos(next),
          },
        };
      });
      return;
    }
    if (event.type === "assistant.external_coding.changed") {
      const codingSessionId = String(event.payload.codingSessionId ?? "");
      if (codingSessionId) {
        useExternalCodingSessionStore.getState().refreshIfCached(codingSessionId);
      }
      set({ needsResync: true });
      return;
    }
    if (event.type === "user_task.changed") {
      // user_task 变更：递增版本号，供 AssistantScreen 刷新用户任务列表 + distribution
      set((state) => ({ userTaskVersion: state.userTaskVersion + 1 }));
      return;
    }
    if (event.type !== "assistant.task_graph.changed") {
      return;
    }
    set((state) => {
      const graphId = String(event.payload.graphId ?? "");
      if (!state.currentGraph || state.currentGraph.graphId !== graphId) {
        return state;
      }
      const taskId = String(event.payload.taskId ?? "");
      if (!taskId) {
        // 图级变更（graph_created / graph_completed / graph_stopped / graph_cancelled / root_failed）
        // 没有 taskId 但图结构已变，必须标记 resync 让前端重新拉权威快照
        const changeType = String(event.payload.changeType ?? "");
        if (GRAPH_LEVEL_CHANGE_TYPES.has(changeType)) {
          return { needsResync: true };
        }
        return state;
      }
      // 增量事件引用了当前权威快照里不存在的 taskId（如新建子任务节点）：图结构已变，
      // 不能静默丢弃，标记 resync 让前端重新拉 typed 权威快照。
      const known = state.currentGraph.tasks.some((task) => task.taskId === taskId);
      if (!known) {
        return { needsResync: true };
      }
      return {
        currentGraph: {
          ...state.currentGraph,
          tasks: state.currentGraph.tasks.map((task) =>
            task.taskId === taskId
              ? {
                  ...task,
                  // payload 已由 parseUiEvent → parseTaskGraphChangedPayload 完成 enum/类型校验，
                  // 缺失字段归一为 null；这里用 ?? 保留旧值，无需再做字段级 typeof 防护。
                  status: event.payload.status ?? task.status,
                  displayPhase: event.payload.displayPhase ?? task.displayPhase,
                  requiresReview: event.payload.requiresReview ?? task.requiresReview,
                  safeExplanation: event.payload.safeExplanation ?? task.safeExplanation,
                  suspendReason: event.payload.suspendReason ?? task.suspendReason,
                }
              : task,
          ),
        },
      };
    });
  },
  markNeedsResync: () => set({ needsResync: true }),
  loadNewTaskTodos: (sessionId, currentTaskIds, currentTaskIdsKey) => {
    // 先计算新 ID，再更新状态，最后触发异步加载（副作用在 set 外）
    const state = get();
    const base =
      state.loadedTodoGraphKey !== currentTaskIdsKey
        ? new Set<string>()
        : state.loadedTodoTaskIds;
    const newIds: string[] = [];
    for (const taskId of currentTaskIds) {
      if (!base.has(taskId)) {
        newIds.push(taskId);
      }
    }
    if (newIds.length === 0 && state.loadedTodoGraphKey === currentTaskIdsKey) {
      return; // 无变化，跳过
    }
    const next = new Set(base);
    for (const id of newIds) {
      next.add(id);
    }
    set({ loadedTodoTaskIds: next, loadedTodoGraphKey: currentTaskIdsKey });
    // 异步加载新 todo（fire-and-forget，在状态提交后触发）
    for (const id of newIds) {
      void get().loadTodos(sessionId, id);
    }
  },
  executeResync: async (sessionId, activeMeetingChannelId, currentTaskIds) => {
    const state = get();
    if (!sessionId || !state.needsResync) return;
    // 先清除标记，防止 effect 重入
    set({ needsResync: false });
    await Promise.all([
      state.loadCurrentGraph(sessionId),
      state.loadBoard(sessionId),
      ...(activeMeetingChannelId
        ? [state.loadMeeting(sessionId, activeMeetingChannelId)]
        : []),
      ...currentTaskIds.map((taskId) => state.loadTodos(sessionId, taskId)),
    ]);
  },
  clearSessionTracking: () =>
    set({ loadedTodoTaskIds: new Set<string>(), loadedTodoGraphKey: "" }),
  closeMeeting: () => set({ activeMeeting: null }),
  setCurrentGraph: (graph) => set({ currentGraph: graph }),
  reset: () => set({
    currentGraph: null,
    boardItems: [],
    activeMeeting: null,
    todosByTaskId: {},
    todoLoadingTaskIds: [],
    loadedTodoTaskIds: new Set<string>(),
    loadedTodoGraphKey: "",
    graphLoading: false,
    boardLoading: false,
    meetingLoading: false,
    graphError: null,
    boardError: null,
    meetingError: null,
    needsResync: false,
    userTaskVersion: 0,
  }),
}));
