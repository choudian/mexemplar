import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("../../src/utils/desktopNotification", () => ({
  sendDesktopNotification: vi.fn().mockResolvedValue(undefined),
}));

import { configureDesktopApi } from "../../src/api/client";
import { useScheduledStore } from "../../src/state/scheduledStore";
import { useToastStore } from "../../src/state/toastStore";
import { sendDesktopNotification } from "../../src/utils/desktopNotification";

const baseTask = {
  scheduledTaskId: "sch_1",
  sourceType: "direct",
  sourceRef: "x",
  title: "查竞品",
  scheduleKind: "recurring",
  scheduleDescription: "每天 09:00",
  status: "active",
  unattendedAutoApprove: false,
  nextFireAt: null,
  lastFireAt: null,
  lastRunOutcome: null,
  lastRunAt: null,
  createdAt: "t",
  updatedAt: "t",
} as any;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise;
  });
  return { promise, resolve };
}

function reset() {
  useScheduledStore.setState({
    hydrated: true,
    tasks: [baseTask],
    tasksTotal: 1,
    taskDetail: null,
    runsByTask: {},
    runsTotalByTask: {},
    expandedTaskIds: new Set<string>(),
    loadingRunsTaskIds: [],
    pendingConfirmation: null,
    submittingConfirmation: false,
    needsResync: false,
  } as any);
}

describe("scheduledStore.applyEvent", () => {
  beforeEach(() => {
    configureDesktopApi({
      baseUrl: "http://desktop.test",
      sessionToken: "tok",
    });
    useToastStore.setState({ toasts: [] } as any);
    vi.mocked(sendDesktopNotification).mockClear();
    reset();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("resetSession POSTs reset endpoint and replaces the task snapshot", async () => {
    const updated = { ...baseTask, updatedAt: "later" };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(updated), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await useScheduledStore.getState().resetSession("sch_1");

    expect(result?.updatedAt).toBe("later");
    expect(useScheduledStore.getState().tasks[0]?.updatedAt).toBe("later");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/scheduled-tasks/sch_1/reset-session",
      expect.objectContaining({ method: "POST" }),
    );
  });

  test("scheduled_task.changed(deleted) removes task from list", () => {
    useScheduledStore.setState({
      taskDetail: baseTask,
      runsByTask: { sch_1: [] },
      runsTotalByTask: { sch_1: 2 },
      expandedTaskIds: new Set(["sch_1"]),
      loadingRunsTaskIds: ["sch_1"],
    });

    useScheduledStore.getState().applyEvent({
      type: "scheduled_task.changed",
      payload: { taskId: "sch_1", changeType: "deleted" },
    } as any);
    const state = useScheduledStore.getState();
    expect(state.tasks).toHaveLength(0);
    expect(state.tasksTotal).toBe(0);
    expect(state.taskDetail).toBeNull();
    expect(state.runsByTask).not.toHaveProperty("sch_1");
    expect(state.runsTotalByTask).not.toHaveProperty("sch_1");
    expect(state.expandedTaskIds.has("sch_1")).toBe(false);
    expect(state.loadingRunsTaskIds).not.toContain("sch_1");

    // REST 乐观删除后又收到权威事件时，计数不能重复递减。
    useScheduledStore.getState().applyEvent({
      type: "scheduled_task.changed",
      payload: { taskId: "sch_1", changeType: "deleted" },
    } as any);
    expect(useScheduledStore.getState().tasksTotal).toBe(0);
  });

  test("scheduled_task.changed without taskId marks resync", () => {
    useScheduledStore.getState().applyEvent({
      type: "scheduled_task.changed",
      payload: { changeType: "created" },
    } as any);
    expect(useScheduledStore.getState().needsResync).toBe(true);
  });

  test("scheduled_task.completed(succeeded) pushes success toast", () => {
    useScheduledStore.getState().applyEvent({
      type: "scheduled_task.completed",
      payload: {
        taskId: "sch_1",
        taskTitle: "查竞品",
        runId: "r",
        sessionId: "s",
        outcome: "succeeded",
        summary: "99 元",
      },
    } as any);
    expect(useToastStore.getState().toasts.length).toBeGreaterThan(0);
    expect(sendDesktopNotification).toHaveBeenCalledOnce();
    expect(sendDesktopNotification).toHaveBeenCalledWith({
      title: "定时任务已完成",
      body: "查竞品",
    });
  });

  test("scheduled_task.completed(failed) pushes warning toast", () => {
    useScheduledStore.getState().applyEvent({
      type: "scheduled_task.completed",
      payload: {
        taskId: "sch_1",
        taskTitle: "查竞品",
        runId: "r",
        sessionId: "s",
        outcome: "failed",
        failureReason: "超时",
      },
    } as any);
    expect(useToastStore.getState().toasts.length).toBeGreaterThan(0);
    expect(sendDesktopNotification).toHaveBeenCalledOnce();
    expect(sendDesktopNotification).toHaveBeenCalledWith({
      title: "定时任务未成功",
      body: "查竞品",
    });
  });

  test("scheduled_task.needs_takeover pushes warning toast", () => {
    useScheduledStore.getState().applyEvent({
      type: "scheduled_task.needs_takeover",
      payload: {
        taskId: "sch_1",
        taskTitle: "查竞品",
        runId: "r",
        sessionId: "s",
        reason: "needs_user_input",
      },
    } as any);
    expect(useToastStore.getState().toasts.length).toBeGreaterThan(0);
    expect(sendDesktopNotification).toHaveBeenCalledOnce();
    expect(sendDesktopNotification).toHaveBeenCalledWith({
      title: "定时任务需要你的帮助",
      body: "查竞品",
    });
  });

  test("scheduling.confirmation_requested sets pendingConfirmation", () => {
    useScheduledStore.getState().applyEvent({
      type: "scheduling.confirmation_requested",
      payload: {
        requestId: "scf_1",
        sessionId: "ast_1",
        draft: {
          title: "查竞品",
          scheduleDescription: "每天 09:00",
          instruction: "查价格",
          scheduleKind: "recurring",
          sourceType: "direct",
        },
        unattendedAutoApprove: false,
        expiresAt: "2099-01-01T00:00:00Z",
      },
    } as any);
    const pending = useScheduledStore.getState().pendingConfirmation;
    expect(pending).not.toBeNull();
    expect(pending?.requestId).toBe("scf_1");
    expect(pending?.status).toBe("pending");
  });

  test("scheduling.confirmation_resolved clears pendingConfirmation", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ items: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    useScheduledStore.getState().applyEvent({
      type: "scheduling.confirmation_requested",
      payload: {
        requestId: "scf_1",
        sessionId: "ast_1",
        draft: {
          title: "T",
          scheduleDescription: "d",
          instruction: "i",
          scheduleKind: "one_shot",
          sourceType: "direct",
        },
        unattendedAutoApprove: false,
        expiresAt: "2099-01-01T00:00:00Z",
      },
    } as any);
    expect(useScheduledStore.getState().pendingConfirmation).not.toBeNull();
    useScheduledStore.getState().applyEvent({
      type: "scheduling.confirmation_resolved",
      payload: { requestId: "scf_1", sessionId: "ast_1", status: "confirmed" },
    } as any);
    expect(useScheduledStore.getState().pendingConfirmation).toBeNull();
  });

  test("resolved event for an older request does not clear the current card", () => {
    useScheduledStore.getState().applyEvent({
      type: "scheduling.confirmation_requested",
      payload: {
        requestId: "scf_current",
        sessionId: "ast_2",
        draft: {
          title: "当前卡",
          scheduleDescription: "每天 09:00",
          instruction: "执行当前任务",
          scheduleKind: "recurring",
          sourceType: "direct",
        },
        unattendedAutoApprove: false,
        expiresAt: "2099-01-01T00:00:00Z",
      },
    } as any);

    useScheduledStore.getState().applyEvent({
      type: "scheduling.confirmation_resolved",
      payload: {
        requestId: "scf_older",
        sessionId: "ast_1",
        status: "confirmed",
      },
    } as any);

    expect(useScheduledStore.getState().pendingConfirmation?.requestId).toBe(
      "scf_current",
    );
  });

  test("late REST response cannot unlock or refresh over a newer submission", async () => {
    const oldResponse = deferred<Response>();
    const currentResponse = deferred<Response>();
    const fetchMock = vi.fn((input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/confirmations/scf_old/decision")) {
        return oldResponse.promise;
      }
      if (url.includes("/confirmations/scf_current/decision")) {
        return currentResponse.promise;
      }
      if (url.endsWith("/confirmations/pending")) {
        return Promise.resolve(
          new Response(JSON.stringify({ items: [] }), {
            status: 200,
            headers: { "Content-Type": "application/json" },
          }),
        );
      }
      return Promise.reject(new Error(`unexpected request: ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    const requestCard = (requestId: string) =>
      useScheduledStore.getState().applyEvent({
        type: "scheduling.confirmation_requested",
        payload: {
          requestId,
          sessionId: "ast_race",
          draft: {
            title: requestId,
            scheduleDescription: "一次性 18:00",
            instruction: "执行",
            scheduleKind: "one_shot",
            sourceType: "direct",
          },
          unattendedAutoApprove: false,
          expiresAt: "2099-01-01T00:00:00Z",
        },
      } as any);

    requestCard("scf_old");
    const oldSubmit = useScheduledStore
      .getState()
      .cancelConfirmation("scf_old");
    requestCard("scf_current");
    const currentSubmit = useScheduledStore
      .getState()
      .cancelConfirmation("scf_current");
    expect(useScheduledStore.getState().submittingConfirmation).toBe(true);

    oldResponse.resolve(new Response(null, { status: 204 }));
    await oldSubmit;

    expect(useScheduledStore.getState().pendingConfirmation?.requestId).toBe(
      "scf_current",
    );
    expect(useScheduledStore.getState().submittingConfirmation).toBe(true);
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith("/confirmations/pending"),
      ),
    ).toBe(false);

    currentResponse.resolve(new Response(null, { status: 204 }));
    await currentSubmit;

    expect(useScheduledStore.getState().pendingConfirmation).toBeNull();
    expect(useScheduledStore.getState().submittingConfirmation).toBe(false);
  });

  test("refreshPendingConfirmation restores a renderable global card", async () => {
    const restored = {
      requestId: "scf_restored",
      sessionId: "ast_previous",
      draft: {
        title: "恢复确认卡",
        scheduleDescription: "一次性 18:00",
        instruction: "恢复后仍可确认的指令",
        scheduleKind: "one_shot",
        sourceType: "direct",
      },
      unattendedAutoApprove: false,
      expiresAt: "2099-01-01T00:00:00Z",
      status: "pending",
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [restored] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    try {
      await useScheduledStore.getState().refreshPendingConfirmation();
    } finally {
      vi.unstubAllGlobals();
    }

    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/scheduled-tasks/confirmations/pending",
      expect.any(Object),
    );
    expect(useScheduledStore.getState().pendingConfirmation).toEqual(restored);
  });

  test("refreshPendingConfirmation surfaces failure and keeps resync pending", async () => {
    const existing = {
      requestId: "scf_existing",
      sessionId: "ast_existing",
      draft: {
        title: "保留旧卡",
        scheduleDescription: "立即",
        instruction: "继续等待",
        scheduleKind: "one_shot",
        sourceType: "direct",
      },
      unattendedAutoApprove: false,
      expiresAt: "2099-01-01T00:00:00Z",
      status: "pending",
    } as const;
    useScheduledStore.setState({ pendingConfirmation: existing, needsResync: false });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network unavailable")));

    await expect(
      useScheduledStore.getState().refreshPendingConfirmation(),
    ).rejects.toThrow("network unavailable");

    expect(useScheduledStore.getState().pendingConfirmation).toEqual(existing);
    expect(useScheduledStore.getState().needsResync).toBe(true);
    expect(useScheduledStore.getState().lastError).toContain("network unavailable");
  });

  test("load propagates authoritative refresh failure after preserving store error state", async () => {
    useScheduledStore.setState({
      lastError: null,
      needsResync: false,
      loading: false,
    });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("list unavailable")));

    await expect(useScheduledStore.getState().load()).rejects.toThrow("list unavailable");

    expect(useScheduledStore.getState().tasks).toEqual([baseTask]);
    expect(useScheduledStore.getState().needsResync).toBe(true);
    expect(useScheduledStore.getState().lastError).toContain("list unavailable");
    expect(useScheduledStore.getState().loading).toBe(false);
  });

  test("backend.resync_required(scheduled domain) marks needsResync", () => {
    useScheduledStore.getState().applyEvent({
      type: "backend.resync_required",
      payload: { reason: "replay_gap", domains: ["scheduled"] },
    } as any);
    expect(useScheduledStore.getState().needsResync).toBe(true);
  });

  test("backend.resync_required(other domain) does NOT mark needsResync", () => {
    useScheduledStore.getState().applyEvent({
      type: "backend.resync_required",
      payload: { reason: "replay_gap", domains: ["brain"] },
    } as any);
    expect(useScheduledStore.getState().needsResync).toBe(false);
  });

  test("markNeedsResync sets flag", () => {
    useScheduledStore.getState().markNeedsResync();
    expect(useScheduledStore.getState().needsResync).toBe(true);
  });
});
