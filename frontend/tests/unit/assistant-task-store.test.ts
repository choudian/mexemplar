import { afterEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import type {
  AssistantTaskBoardItem,
  AssistantTaskGraphSnapshot,
} from "../../src/api/assistantTasks";
import type { AssistantTodoItem } from "../../src/api/assistantTasks";
import { useAssistantTaskStore } from "../../src/state/assistantTaskStore";

const GRAPH: AssistantTaskGraphSnapshot = {
  graphId: "tg_1",
  sessionId: "ast_1",
  userMessageSequence: 1,
  version: 1,
  tasks: [
    {
      taskId: "tsk_1",
      graphId: "tg_1",
      parentTaskId: null,
      title: "整理报销",
      descriptionPreview: "整理本月报销",
      status: "running",
      displayPhase: "running",
      requiresReview: false,
      requiresConfirmation: false,
      safeExplanation: "",
      suspendReason: null,
      assignee: null,
      adjudicationId: null,
      updatedAt: "2026-06-17T12:00:00Z",
    },
  ],
  edges: [],
  adjudications: [],
};

const BOARD: { items: AssistantTaskBoardItem[] } = {
  items: [
    {
      taskId: "tsk_board",
      graphId: "tg_1",
      title: "核对发票",
      status: "pending_dispatch",
      claimStatus: "open",
      assignee: null,
      updatedAt: "2026-06-17T12:00:00Z",
    },
  ],
};

const MEETING = {
  channelId: "mtg_1",
  status: "open",
  participants: [{ type: "specialist", id: "sp_a" }],
  turnsUsed: 1,
  turnBudget: 12,
  messages: [{ sequence: 1, senderId: "sp_a", content: "按日期排序。" }],
  nextAfterSequence: null,
  conclusion: null,
};

const TODO_ITEMS: AssistantTodoItem[] = [
  { todoId: "todo_1", text: "收集发票", status: "todo", sortOrder: 1 },
  { todoId: "todo_2", text: "核对金额", status: "doing", sortOrder: 2 },
];

const TODOS = {
  taskId: "tsk_1",
  items: TODO_ITEMS,
};

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}

describe("assistantTaskStore", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    configureDesktopApi({ baseUrl: "", sessionToken: "" });
    useAssistantTaskStore.getState().reset();
  });

  test("loads current graph snapshot through typed API", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ graph: GRAPH }));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().loadCurrentGraph("ast_1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assistant/sessions/ast_1/task-graphs/current",
      expect.objectContaining({ headers: expect.objectContaining({ "Content-Type": "application/json" }) }),
    );
    expect(useAssistantTaskStore.getState().currentGraph?.graphId).toBe("tg_1");
    expect(useAssistantTaskStore.getState().graphLoading).toBe(false);
  });

  test("applies public graph changed event to current graph", () => {
    useAssistantTaskStore.getState().setCurrentGraph(GRAPH);

    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_1",
      sequence: 2,
      sessionId: "ui_sess_1",
      type: "assistant.task_graph.changed",
      scope: { sessionId: "ast_1" },
      payload: {
        graphId: "tg_1",
        taskId: "tsk_1",
        changeType: "task_updated",
        status: "suspended",
        displayPhase: "paused",
        requiresReview: false,
        safeExplanation: "等待继续",
        suspendReason: "user_stop",
      },
      createdAt: "2026-06-17T12:00:01Z",
    });

    const task = useAssistantTaskStore.getState().currentGraph?.tasks[0];
    expect(task?.status).toBe("suspended");
    expect(task?.displayPhase).toBe("paused");
    expect(task?.suspendReason).toBe("user_stop");
  });

  test("marks resync when graph event references an unknown task", () => {
    useAssistantTaskStore.getState().setCurrentGraph(GRAPH);

    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_unknown_task",
      sequence: 2,
      sessionId: "ui_sess_1",
      type: "assistant.task_graph.changed",
      scope: { sessionId: "ast_1" },
      payload: {
        graphId: "tg_1",
        taskId: "tsk_new_child",
        changeType: "task_created",
        status: "pending_dispatch",
        displayPhase: "running",
      },
      createdAt: "2026-06-17T12:00:01Z",
    });

    // 不静默丢弃新建子任务节点：标记 resync 等待权威快照
    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
    expect(useAssistantTaskStore.getState().currentGraph?.tasks).toHaveLength(1);
  });

  test("marks task graph resync domain as needing reload", () => {
    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_resync",
      sequence: 3,
      sessionId: "ui_sess_1",
      type: "backend.resync_required",
      scope: {},
      payload: { reason: "replay_gap", domains: ["assistant_tasks"] },
      createdAt: "2026-06-17T12:00:02Z",
    });

    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("loads board and meeting snapshots through typed APIs", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(BOARD))
      .mockResolvedValueOnce(jsonResponse(MEETING));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().loadBoard("ast_1");
    await useAssistantTaskStore.getState().loadMeeting("ast_1", "mtg_1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/assistant/sessions/ast_1/task-board",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/assistant/sessions/ast_1/meetings/mtg_1",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
    expect(useAssistantTaskStore.getState().boardItems[0].taskId).toBe("tsk_board");
    expect(useAssistantTaskStore.getState().activeMeeting?.channelId).toBe("mtg_1");
  });

  test("loads task todo snapshot through typed API", async () => {
    const fetchMock = vi.fn(async () => jsonResponse(TODOS));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().loadTodos("ast_1", "tsk_1");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assistant/sessions/ast_1/tasks/tsk_1/todos",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
    expect(useAssistantTaskStore.getState().todosByTaskId.tsk_1).toHaveLength(2);
    expect(useAssistantTaskStore.getState().todoLoadingTaskIds).toHaveLength(0);
  });

  test("optimistically updates todos then accepts authoritative response", async () => {
    useAssistantTaskStore.setState({ todosByTaskId: { tsk_1: TODO_ITEMS } });
    let resolveFetch!: (value: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const nextItems: AssistantTodoItem[] = [
      { todoId: "todo_1", text: "收集发票", status: "done", sortOrder: 1 },
    ];
    const updatePromise = useAssistantTaskStore
      .getState()
      .updateTodos("ast_1", "tsk_1", "specialist", "sp_1", nextItems);

    expect(useAssistantTaskStore.getState().todosByTaskId.tsk_1[0].status).toBe("done");
    expect(useAssistantTaskStore.getState().todoLoadingTaskIds).toContain("tsk_1");

    resolveFetch(jsonResponse({ taskId: "tsk_1", items: nextItems }));
    await updatePromise;

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/assistant/sessions/ast_1/tasks/tsk_1/todos",
      expect.objectContaining({ method: "PUT" }),
    );
    expect(useAssistantTaskStore.getState().todosByTaskId.tsk_1[0].status).toBe("done");
    expect(useAssistantTaskStore.getState().todoLoadingTaskIds).toHaveLength(0);
  });

  test("applies board and meeting public events", () => {
    useAssistantTaskStore.setState({ boardItems: BOARD.items });

    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_board",
      sequence: 4,
      sessionId: "ui_sess_1",
      type: "assistant.task_board.changed",
      scope: { sessionId: "ast_1" },
      payload: {
        taskId: "tsk_board",
        graphId: "tg_1",
        changeType: "claimed",
        claimStatus: "claimed",
      },
      createdAt: "2026-06-17T12:00:03Z",
    });
    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_meeting",
      sequence: 5,
      sessionId: "ui_sess_1",
      type: "assistant.meeting.changed",
      scope: { sessionId: "ast_1" },
      payload: {
        channelId: "mtg_1",
        graphId: "tg_1",
        changeType: "message_added",
      },
      createdAt: "2026-06-17T12:00:04Z",
    });

    expect(useAssistantTaskStore.getState().boardItems[0].claimStatus).toBe("claimed");
    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("applies todo public events and marks missing todo for resync", () => {
    useAssistantTaskStore.setState({ todosByTaskId: { tsk_1: TODO_ITEMS } });

    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_todo",
      sequence: 6,
      sessionId: "ui_sess_1",
      type: "assistant.todo.changed",
      scope: { sessionId: "ast_1" },
      payload: {
        taskId: "tsk_1",
        todoId: "todo_1",
        changeType: "updated",
        status: "done",
        sortOrder: 3,
      },
      createdAt: "2026-06-17T12:00:05Z",
    });

    const todos = useAssistantTaskStore.getState().todosByTaskId.tsk_1;
    expect(todos.at(-1)?.todoId).toBe("todo_1");
    expect(todos.at(-1)?.status).toBe("done");

    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_todo_missing",
      sequence: 7,
      sessionId: "ui_sess_1",
      type: "assistant.todo.changed",
      scope: { sessionId: "ast_1" },
      payload: {
        taskId: "tsk_1",
        todoId: "todo_missing",
        changeType: "updated",
      },
      createdAt: "2026-06-17T12:00:06Z",
    });

    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("marks resync for todo deleted and reordered change types", () => {
    // deleted/reordered 改变集合结构或批量顺序，单条局部更新无法表达；必须 resync 拉权威
    // 快照，否则已删 todo 残留 UI、重排顺序错乱（CLAUDE.md: assistant.todo.changed 只做局部提示）。
    useAssistantTaskStore.setState({ todosByTaskId: { tsk_1: TODO_ITEMS }, needsResync: false });

    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_todo_deleted",
      sequence: 10,
      sessionId: "ui_sess_1",
      type: "assistant.todo.changed",
      scope: { sessionId: "ast_1" },
      payload: { taskId: "tsk_1", todoId: "todo_1", changeType: "deleted" },
      createdAt: "2026-06-17T12:00:09Z",
    });
    expect(useAssistantTaskStore.getState().needsResync).toBe(true);

    useAssistantTaskStore.setState({ needsResync: false });
    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_todo_reordered",
      sequence: 11,
      sessionId: "ui_sess_1",
      type: "assistant.todo.changed",
      scope: { sessionId: "ast_1" },
      payload: { taskId: "tsk_1", todoId: "todo_1", changeType: "reordered", sortOrder: 5 },
      createdAt: "2026-06-17T12:00:10Z",
    });
    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("marks todo resync domain as needing reload", () => {
    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_resync_todos",
      sequence: 8,
      sessionId: "ui_sess_1",
      type: "backend.resync_required",
      scope: {},
      payload: { reason: "replay_gap", domains: ["assistant_todos"] },
      createdAt: "2026-06-17T12:00:07Z",
    });

    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("stops graph then reloads authoritative snapshot", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ accepted: true, graphId: "tg_1", affectedTaskCount: 1 }))
      .mockResolvedValueOnce(jsonResponse(GRAPH));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().stopGraph("ast_1", "tg_1", "run_1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/assistant/sessions/ast_1/task-graphs/tg_1/stop",
      expect.objectContaining({ method: "POST" }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/assistant/sessions/ast_1/task-graphs/tg_1",
      expect.objectContaining({ headers: expect.any(Object) }),
    );
    expect(useAssistantTaskStore.getState().currentGraph?.graphId).toBe("tg_1");
  });

  test("decides adjudication then reloads returned graph", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          accepted: true,
          adjudicationId: "adj_1",
          taskId: "tsk_1",
          graphId: "tg_1",
          decision: "accepted",
          taskStatus: "done",
        }),
      )
      .mockResolvedValueOnce(jsonResponse(GRAPH));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().decideAdjudication("ast_1", "adj_1", "accepted");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/assistant/sessions/ast_1/task-adjudications/adj_1/decision",
      expect.objectContaining({ method: "POST" }),
    );
    expect(useAssistantTaskStore.getState().graphLoading).toBe(false);
  });

  test("sets error when graph load fails", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 500,
      text: async () => '{"detail":"Internal Server Error"}',
    }));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().loadCurrentGraph("ast_1");

    expect(useAssistantTaskStore.getState().graphError).toBeTruthy();
    expect(useAssistantTaskStore.getState().graphLoading).toBe(false);
    expect(useAssistantTaskStore.getState().currentGraph).toBeNull();
  });

  test("marks resync when board load fails", async () => {
    // resync effect 并发 fire-and-forget 各 load；某个 load 静默失败时不能被其他成功
    // 的 load 清掉 needsResync，失败域必须（重）设 flag 等待下次 resync 重拉权威快照。
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 500,
      text: async () => '{"detail":"Internal Server Error"}',
    }));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().loadBoard("ast_1");

    expect(useAssistantTaskStore.getState().boardError).toBeTruthy();
    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("marks resync when meeting load fails", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 500,
      text: async () => '{"detail":"Internal Server Error"}',
    }));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().loadMeeting("ast_1", "mtg_1");

    expect(useAssistantTaskStore.getState().meetingError).toBeTruthy();
    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("marks resync when todos load fails", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 500,
      text: async () => '{"detail":"Internal Server Error"}',
    }));
    vi.stubGlobal("fetch", fetchMock);

    await useAssistantTaskStore.getState().loadTodos("ast_1", "tsk_1");

    expect(useAssistantTaskStore.getState().todoLoadingTaskIds).toHaveLength(0);
    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });

  test("reverts optimistic todos on API failure", async () => {
    useAssistantTaskStore.setState({ todosByTaskId: { tsk_1: TODO_ITEMS } });
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 422,
      text: async () => '{"detail":"Validation Error"}',
    }));
    vi.stubGlobal("fetch", fetchMock);

    const nextItems: AssistantTodoItem[] = [
      { todoId: "todo_1", text: "收集发票", status: "done", sortOrder: 1 },
    ];
    await useAssistantTaskStore
      .getState()
      .updateTodos("ast_1", "tsk_1", "specialist", "sp_1", nextItems);

    expect(useAssistantTaskStore.getState().todoLoadingTaskIds).toHaveLength(0);
    expect(useAssistantTaskStore.getState().todosByTaskId.tsk_1[0].status).toBe("todo");
  });

  test("marks resync when optimistic todo revert may clobber concurrent event", async () => {
    // API in-flight 期间收到 todo.changed 更新了同 taskId 的另一条 todo；API 失败回滚
    // 用闭包 previous 整盘覆盖，会丢掉那条事件驱动更新。回滚必须标记 needsResync 让
    // 前端重新拉权威快照，而非静默覆盖事件更新。
    useAssistantTaskStore.setState({ todosByTaskId: { tsk_1: TODO_ITEMS }, needsResync: false });
    let resolveFetch!: (value: Response) => void;
    const fetchMock = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          resolveFetch = resolve;
        }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const optimistic: AssistantTodoItem[] = [
      { todoId: "todo_1", text: "收集发票", status: "done", sortOrder: 1 },
      { todoId: "todo_2", text: "核对金额", status: "doing", sortOrder: 2 },
    ];
    const updatePromise = useAssistantTaskStore
      .getState()
      .updateTodos("ast_1", "tsk_1", "specialist", "sp_1", optimistic);

    // API in-flight 期间，事件更新了另一条 todo（todo_2 → done）
    useAssistantTaskStore.getState().applyEvent({
      eventId: "evt_concurrent_todo",
      sequence: 9,
      sessionId: "ui_sess_1",
      type: "assistant.todo.changed",
      scope: { sessionId: "ast_1" },
      payload: {
        taskId: "tsk_1",
        todoId: "todo_2",
        changeType: "updated",
        status: "done",
        sortOrder: 2,
      },
      createdAt: "2026-06-17T12:00:08Z",
    });
    expect(useAssistantTaskStore.getState().todosByTaskId.tsk_1[1].status).toBe("done");

    // API 失败 → 整盘回滚覆盖 previous，事件更新被吞；必须标记 resync
    resolveFetch({ ok: false, status: 422, text: async () => '{"detail":"Validation"}' } as Response);
    await updatePromise;

    expect(useAssistantTaskStore.getState().needsResync).toBe(true);
  });
});
