import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import {
  afterAll,
  afterEach,
  beforeEach,
  describe,
  expect,
  test,
  vi,
} from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { ScheduledScreen } from "../../src/screens/ScheduledScreen/ScheduledScreen";
import { useAssistantStore } from "../../src/state/assistantStore";
import { useScheduledStore } from "../../src/state/scheduledStore";
import { useShellStore } from "../../src/state/shellStore";
import { useToastStore } from "../../src/state/toastStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  };
}

function emptyResponse() {
  return { ok: true, status: 204, json: async () => null };
}

const baseTask = {
  scheduledTaskId: "sch_1",
  sourceType: "direct",
  sourceRef: "查竞品",
  title: "查竞品价格",
  scheduleKind: "recurring",
  scheduleDescription: "每天 09:00",
  status: "active",
  unattendedAutoApprove: false,
  nextFireAt: "2026-07-19T01:00:00Z",
  lastFireAt: "2026-07-18T01:00:00Z",
  lastRunOutcome: "succeeded",
  lastRunAt: "2026-07-18T01:30:00Z",
  createdAt: "2026-07-17T10:00:00Z",
  updatedAt: "2026-07-18T01:30:00Z",
};

const originalSelectSession = useAssistantStore.getState().selectSession;
const originalSendDraft = useAssistantStore.getState().sendDraft;

describe("ScheduledScreen", () => {
  beforeEach(() => {
    configureDesktopApi({
      baseUrl: "http://desktop.test",
      sessionToken: "token",
    });
    useScheduledStore.setState({
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
    });
    useToastStore.setState({ toasts: [] });
    useAssistantStore.setState({
      activeSessionId: null,
      draft: "",
      draftBySession: {},
      selectSession: originalSelectSession,
      sendDraft: originalSendDraft,
    });
    useShellStore.setState({ activeRoute: "scheduled" });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  afterAll(() => {
    useAssistantStore.setState({
      selectSession: originalSelectSession,
      sendDraft: originalSendDraft,
    });
    useShellStore.setState({ activeRoute: "assistant" });
  });

  test("renders the empty state with example prompts when no tasks exist", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ items: [], total: 0, limit: 200, offset: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);

    await waitFor(() =>
      expect(screen.getByText("还没有定时任务")).toBeInTheDocument(),
    );
    // 例句在空态里展示（FR-020），引导用户去对话创建。
    expect(
      screen.getByText(/现在就帮我看一下今天的会议安排/),
    ).toBeInTheDocument();
  });

  test("shows task row with title, status, schedule, next fire and last run labels", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ items: [baseTask], total: 1, limit: 200, offset: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);

    await screen.findByText("查竞品价格");
    expect(screen.getByText("运行中")).toBeInTheDocument();
    expect(screen.getByText("每天 09:00")).toBeInTheDocument();
    expect(screen.getByText(/还没跑过|上次执行/)).toBeInTheDocument();
  });

  test("renders timezone-less UTC API timestamps in the user's local timezone", async () => {
    const task = {
      ...baseTask,
      title: "UTC 时间展示",
      nextFireAt: "2026-07-21T07:00:00",
      lastRunAt: "2026-07-20T07:00:00",
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ items: [task], total: 1, limit: 200, offset: 0 }),
      ),
    );
    const formatter = new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });

    render(<ScheduledScreen />);

    await screen.findByText("UTC 时间展示");
    expect(
      screen.getByText(`下次 ${formatter.format(new Date("2026-07-21T07:00:00Z"))}`),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        `上次执行 ${formatter.format(new Date("2026-07-20T07:00:00Z"))} · 成功`,
      ),
    ).toBeInTheDocument();
  });

  test("marks unattended-auto-approve tasks with a prominent badge in the list (FR-019)", async () => {
    const task = { ...baseTask, unattendedAutoApprove: true };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({ items: [task], total: 1, limit: 200, offset: 0 }),
      ),
    );

    render(<ScheduledScreen />);

    await screen.findByText("查竞品价格");
    expect(screen.getByText("已授权免确认")).toBeInTheDocument();
  });

  test("pause button calls PATCH with status=paused and shows toast", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (
          url === "http://desktop.test/api/scheduled-tasks/sch_1" &&
          init?.method === "PATCH"
        ) {
          const body = JSON.parse(String(init.body));
          expect(body).toEqual({ status: "paused" });
          return jsonResponse({ ...baseTask, status: "paused" });
        }
        return jsonResponse({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    fireEvent.click(screen.getByRole("button", { name: "暂停" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/scheduled-tasks/sch_1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ status: "paused" }),
        }),
      ),
    );
    await waitFor(() =>
      expect(
        useToastStore
          .getState()
          .toasts.some((t) => t.message.includes("已暂停")),
      ).toBe(true),
    );
  });

  test("resume button shows for paused tasks and PATCHes status=active", async () => {
    const pausedTask = { ...baseTask, status: "paused" as const };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [pausedTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (
          url.endsWith("/api/scheduled-tasks/sch_1") &&
          init?.method === "PATCH"
        ) {
          return jsonResponse({ ...pausedTask, status: "active" });
        }
        return jsonResponse({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    expect(screen.getByRole("button", { name: "现在跑一次" })).toBeEnabled();
    fireEvent.click(screen.getByRole("button", { name: "启用" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/scheduled-tasks/sch_1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ status: "active" }),
        }),
      ),
    );
  });

  test("completed tasks do not show pause/resume but still show fire-now and delete", async () => {
    const completedTask = {
      ...baseTask,
      status: "completed" as const,
      scheduleKind: "one_shot" as const,
    };
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        jsonResponse({
          items: [completedTask],
          total: 1,
          limit: 200,
          offset: 0,
        }),
      ),
    );

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    expect(
      screen.queryByRole("button", { name: "暂停" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "启用" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "现在跑一次" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "删除查竞品价格" }),
    ).toBeInTheDocument();
  });

  test("fire-now button POSTs fire-now endpoint and shows info toast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (
          url.endsWith("/api/scheduled-tasks/sch_1/fire-now") &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            runId: "schr_fire_now",
            scheduledTaskId: "sch_1",
            sessionId: "ast_fire_now",
            startedAt: "2026-07-19T01:00:00Z",
            finishedAt: null,
            status: "running",
            summary: null,
            failureReason: null,
          });
        }
        return jsonResponse({});
      }),
    );

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    fireEvent.click(screen.getByRole("button", { name: "现在跑一次" }));

    await waitFor(() =>
      expect(
        useToastStore
          .getState()
          .toasts.some((t) => t.message.includes("已触发")),
      ).toBe(true),
    );
  });

  test("fire-now failure never shows a false success toast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (
          url.endsWith("/api/scheduled-tasks/sch_1/fire-now") &&
          init?.method === "POST"
        ) {
          return new Response(
            JSON.stringify({ detail: "scheduler_runtime_unavailable" }),
            {
              status: 503,
              headers: { "Content-Type": "application/json" },
            },
          );
        }
        return jsonResponse({});
      }),
    );

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    fireEvent.click(screen.getByRole("button", { name: "现在跑一次" }));

    await waitFor(() =>
      expect(
        useToastStore
          .getState()
          .toasts.some((t) => t.message.includes("没能触发")),
      ).toBe(true),
    );
    expect(
      useToastStore.getState().toasts.some((t) => t.message.includes("已触发")),
    ).toBe(false);
  });

  test("expanded detail can safely reset the task session", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (url.endsWith("/api/scheduled-tasks/sch_1/runs?limit=50&offset=0")) {
          return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
        }
        if (
          url.endsWith("/api/scheduled-tasks/sch_1/reset-session") &&
          init?.method === "POST"
        ) {
          return jsonResponse({ ...baseTask, updatedAt: "2026-07-21T00:00:00Z" });
        }
        return jsonResponse({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");
    fireEvent.click(
      screen.getByRole("button", { name: "展开任务执行记录" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: "重开一轮" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/scheduled-tasks/sch_1/reset-session",
        expect.objectContaining({ method: "POST" }),
      ),
    );
    expect(
      useToastStore
        .getState()
        .toasts.some((toast) => toast.message.includes("下一次会使用新会话")),
    ).toBe(true);
  });

  test("delete button soft-deletes via DELETE and shows toast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (
          url === "http://desktop.test/api/scheduled-tasks/sch_1" &&
          init?.method === "DELETE"
        ) {
          return emptyResponse();
        }
        return jsonResponse({});
      }),
    );

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    fireEvent.click(screen.getByRole("button", { name: "删除查竞品价格" }));

    await waitFor(() =>
      expect(
        useToastStore
          .getState()
          .toasts.some((t) => t.message.includes("已删除")),
      ).toBe(true),
    );
  });

  test("delete failure keeps the row and never shows a false success toast", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (
          url === "http://desktop.test/api/scheduled-tasks/sch_1" &&
          init?.method === "DELETE"
        ) {
          return new Response(JSON.stringify({ detail: "delete_failed" }), {
            status: 500,
            headers: { "Content-Type": "application/json" },
          });
        }
        return jsonResponse({});
      }),
    );

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    fireEvent.click(screen.getByRole("button", { name: "删除查竞品价格" }));

    await waitFor(() =>
      expect(
        useToastStore
          .getState()
          .toasts.some((t) => t.message.includes("没能删除")),
      ).toBe(true),
    );
    expect(screen.getByText("查竞品价格")).toBeInTheDocument();
    expect(
      useToastStore.getState().toasts.some((t) => t.message.includes("已删除")),
    ).toBe(false);
  });

  test("expanded detail shows close-unattended toggle when auto-approve is on", async () => {
    const task = { ...baseTask, unattendedAutoApprove: true };
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [task],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (url.includes("/api/scheduled-tasks/sch_1/runs")) {
          return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
        }
        if (
          url.endsWith("/api/scheduled-tasks/sch_1") &&
          init?.method === "PATCH"
        ) {
          return jsonResponse({ ...task, unattendedAutoApprove: false });
        }
        return jsonResponse({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    // 展开：点 head 按钮。
    fireEvent.click(screen.getByRole("button", { name: /展开任务执行记录/ }));
    await waitFor(() =>
      expect(screen.getByText("免确认授权")).toBeInTheDocument(),
    );
    expect(screen.getByText(/已开启/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "收回授权" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/scheduled-tasks/sch_1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ unattendedAutoApprove: false }),
        }),
      ),
    );
  });

  test("expanded detail can explicitly enable unattended authorization", async () => {
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (url.includes("/api/scheduled-tasks/sch_1/runs")) {
          return jsonResponse({ items: [], total: 0, limit: 50, offset: 0 });
        }
        if (
          url.endsWith("/api/scheduled-tasks/sch_1") &&
          init?.method === "PATCH"
        ) {
          return jsonResponse({ ...baseTask, unattendedAutoApprove: true });
        }
        return jsonResponse({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");

    fireEvent.click(screen.getByRole("button", { name: /展开任务执行记录/ }));
    await screen.findByRole("button", { name: "开启授权" });
    fireEvent.click(screen.getByRole("button", { name: "开启授权" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/scheduled-tasks/sch_1",
        expect.objectContaining({
          method: "PATCH",
          body: JSON.stringify({ unattendedAutoApprove: true }),
        }),
      ),
    );
    await waitFor(() =>
      expect(
        useToastStore
          .getState()
          .toasts.some((toast) => toast.message.includes("已开启")),
      ).toBe(true),
    );
  });

  test("succeeded history opens its existing session without takeover", async () => {
    const selectSession = vi.fn(async () => undefined);
    useAssistantStore.setState({ selectSession });
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
        return jsonResponse({
          items: [baseTask],
          total: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (url.includes("/api/scheduled-tasks/sch_1/runs")) {
        return jsonResponse({
          items: [
            {
              runId: "schr_succeeded",
              scheduledTaskId: "sch_1",
              sessionId: "ast_succeeded",
              startedAt: "2026-07-19T01:00:00Z",
              finishedAt: "2026-07-19T01:05:00Z",
              status: "succeeded",
              summary: "已完成",
              failureReason: null,
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");
    fireEvent.click(screen.getByRole("button", { name: /展开任务执行记录/ }));
    const openButton = await screen.findByRole("button", {
      name: "查看会话",
    });
    await act(async () => {
      openButton.click();
      await new Promise<void>((resolve) => {
        setTimeout(resolve, 0);
      });
    });
    expect(selectSession).toHaveBeenCalledWith("ast_succeeded");
    expect(openButton).toBeEnabled();
    expect(useShellStore.getState().activeRoute).toBe("assistant");
    expect(
      fetchMock.mock.calls.some(([input]) =>
        String(input).endsWith("/takeover"),
      ),
    ).toBe(false);
  });

  test.each([
    ["waiting_user", "去帮一把"],
    ["failed", "接着处理"],
  ])(
    "%s history takes over before opening the returned session",
    async (status, openLabel) => {
      const selectSession = vi.fn(async () => undefined);
      useAssistantStore.setState({ selectSession });
      const fetchMock = vi.fn(
        async (input: RequestInfo | URL, init?: RequestInit) => {
          const url = String(input);
          if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
            return jsonResponse({
              items: [baseTask],
              total: 1,
              limit: 200,
              offset: 0,
            });
          }
          if (url.includes("/api/scheduled-tasks/sch_1/runs?")) {
            return jsonResponse({
              items: [
                {
                  runId: `schr_${status}`,
                  scheduledTaskId: "sch_1",
                  sessionId: `ast_${status}`,
                  startedAt: "2026-07-19T01:00:00Z",
                  finishedAt: null,
                  status,
                  summary: null,
                  failureReason: status === "failed" ? "执行失败" : null,
                },
              ],
              total: 1,
              limit: 50,
              offset: 0,
            });
          }
          if (
            url.endsWith(`/runs/schr_${status}/takeover`) &&
            init?.method === "POST"
          ) {
            return jsonResponse({ sessionId: `ast_taken_${status}` });
          }
          return jsonResponse({});
        },
      );
      vi.stubGlobal("fetch", fetchMock);

      render(<ScheduledScreen />);
      await screen.findByText("查竞品价格");
      fireEvent.click(screen.getByRole("button", { name: /展开任务执行记录/ }));
      const openButton = await screen.findByRole("button", {
        name: openLabel,
      });
      await act(async () => {
        openButton.click();
        await new Promise<void>((resolve) => {
          setTimeout(resolve, 0);
        });
      });
      expect(selectSession).toHaveBeenCalledWith(`ast_taken_${status}`);
      expect(openButton).toBeEnabled();
      expect(useShellStore.getState().activeRoute).toBe("assistant");
      expect(fetchMock).toHaveBeenCalledWith(
        `http://desktop.test/api/scheduled-tasks/sch_1/runs/schr_${status}/takeover`,
        expect.objectContaining({ method: "POST" }),
      );
    },
  );

  test("failed takeover places a recovered instruction into an empty assistant draft", async () => {
    const selectSession = vi.fn(async () => {
      useAssistantStore.setState({
        activeSessionId: "ast_repaired",
        draft: "",
      });
    });
    useAssistantStore.setState({ selectSession, draft: "" });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (url.includes("/api/scheduled-tasks/sch_1/runs?")) {
          return jsonResponse({
            items: [
              {
                runId: "schr_repair",
                scheduledTaskId: "sch_1",
                sessionId: "ast_missing",
                startedAt: "2026-07-19T01:00:00Z",
                finishedAt: "2026-07-19T01:01:00Z",
                status: "failed",
                summary: null,
                failureReason: "启动失败",
              },
            ],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        if (url.endsWith("/runs/schr_repair/takeover") && init?.method === "POST") {
          return jsonResponse({
            sessionId: "ast_repaired",
            recoveryDraft: "重新整理这份周报",
          });
        }
        return jsonResponse({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");
    fireEvent.click(screen.getByRole("button", { name: /展开任务执行记录/ }));
    const openButton = await screen.findByRole("button", { name: "接着处理" });
    await act(async () => {
      openButton.click();
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });

    expect(selectSession).toHaveBeenCalledWith("ast_repaired");
    expect(useAssistantStore.getState().draft).toBe("重新整理这份周报");
    expect(useShellStore.getState().activeRoute).toBe("assistant");
  });

  test("failed takeover preserves an existing target-session draft", async () => {
    const sendDraft = vi.fn(async () => undefined);
    const selectSession = vi.fn(async () => {
      useAssistantStore.setState({
        activeSessionId: "ast_repaired_with_draft",
        draft: "用户正在写的内容",
        draftBySession: {
          ast_repaired_with_draft: "用户正在写的内容",
        },
      });
    });
    useAssistantStore.setState({
      selectSession,
      sendDraft,
      draft: "",
      draftBySession: {},
    });
    const fetchMock = vi.fn(
      async (input: RequestInfo | URL, init?: RequestInit) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
          return jsonResponse({
            items: [baseTask],
            total: 1,
            limit: 200,
            offset: 0,
          });
        }
        if (url.includes("/api/scheduled-tasks/sch_1/runs?")) {
          return jsonResponse({
            items: [
              {
                runId: "schr_repair_with_draft",
                scheduledTaskId: "sch_1",
                sessionId: "ast_existing_empty",
                startedAt: "2026-07-19T01:00:00Z",
                finishedAt: "2026-07-19T01:01:00Z",
                status: "failed",
                summary: null,
                failureReason: "启动失败",
              },
            ],
            total: 1,
            limit: 50,
            offset: 0,
          });
        }
        if (
          url.endsWith("/runs/schr_repair_with_draft/takeover") &&
          init?.method === "POST"
        ) {
          return jsonResponse({
            sessionId: "ast_repaired_with_draft",
            recoveryDraft: "后端恢复出来的任务指令",
          });
        }
        return jsonResponse({});
      },
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");
    fireEvent.click(screen.getByRole("button", { name: /展开任务执行记录/ }));
    const openButton = await screen.findByRole("button", { name: "接着处理" });
    await act(async () => {
      openButton.click();
      await new Promise<void>((resolve) => setTimeout(resolve, 0));
    });

    expect(selectSession).toHaveBeenCalledWith("ast_repaired_with_draft");
    expect(useAssistantStore.getState().draft).toBe("用户正在写的内容");
    expect(sendDraft).not.toHaveBeenCalled();
    expect(useShellStore.getState().activeRoute).toBe("assistant");
  });

  test("skipped runs expose no fake session navigation", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("http://desktop.test/api/scheduled-tasks?")) {
        return jsonResponse({
          items: [baseTask],
          total: 1,
          limit: 200,
          offset: 0,
        });
      }
      if (url.includes("/api/scheduled-tasks/sch_1/runs")) {
        return jsonResponse({
          items: [
            {
              runId: "schr_skipped",
              scheduledTaskId: "sch_1",
              sessionId: null,
              startedAt: "2026-07-19T01:00:00Z",
              finishedAt: "2026-07-19T01:00:00Z",
              status: "skipped",
              summary: null,
              failureReason: null,
            },
          ],
          total: 1,
          limit: 50,
          offset: 0,
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ScheduledScreen />);
    await screen.findByText("查竞品价格");
    fireEvent.click(screen.getByRole("button", { name: /展开任务执行记录/ }));

    const openButton = await screen.findByRole("button", { name: "查看会话" });
    expect(openButton).toBeDisabled();
    expect(fetchMock).not.toHaveBeenCalledWith(
      expect.stringContaining("/takeover"),
      expect.anything(),
    );
  });
});
