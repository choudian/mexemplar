import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { UserTodoScreen } from "../../src/screens/UserTodoScreen/UserTodoScreen";
import { useAssistantStore } from "../../src/state/assistantStore";
import { useScheduledStore } from "../../src/state/scheduledStore";
import { useShellStore } from "../../src/state/shellStore";
import { useToastStore } from "../../src/state/toastStore";
import { useUserTodoStore } from "../../src/state/userTodoStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  };
}

const baseTodo = {
  todoId: "utodo_1",
  title: "准备会议",
  description: "整理议程",
  status: "pending",
  priority: "high",
  sortOrder: 0,
  createdAt: "2026-06-27T01:00:00Z",
  updatedAt: "2026-06-27T01:00:00Z",
  completedAt: null,
};

describe("UserTodoScreen", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useUserTodoStore.setState({
      hydrated: false,
      items: [],
      total: 0,
      statusFilter: "open",
      sort: "created_desc",
      query: "",
      draft: { title: "", description: "", priority: "medium" },
      busy: false,
      lastError: null,
    });
    useScheduledStore.setState({
      hydrated: true,
      tasks: [],
      tasksTotal: 0,
    });
    useShellStore.setState({ activeRoute: "user-todos" });
    useAssistantStore.setState({ draft: "" });
    useToastStore.setState({ toasts: [] });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("loads todos and creates a new one", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.startsWith("http://desktop.test/api/user-todos?")) {
        return jsonResponse({ items: [baseTodo], total: 1, limit: 200, offset: 0 });
      }
      if (url === "http://desktop.test/api/user-todos" && init?.method === "POST") {
        return jsonResponse({
          ...baseTodo,
          todoId: "utodo_2",
          title: "买牛奶",
          priority: "medium",
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UserTodoScreen />);

    await screen.findByText("准备会议");
    fireEvent.change(screen.getByLabelText("待办标题"), { target: { value: "买牛奶" } });
    fireEvent.click(screen.getByRole("button", { name: "新增" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/user-todos",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            title: "买牛奶",
            description: "",
            priority: "medium",
          }),
        }),
      ),
    );
  });

  test("completes a todo and changes filters", async () => {
    const completedTodo = { ...baseTodo, status: "done", completedAt: "2026-06-27T02:00:00Z" };
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.includes("/api/user-todos/utodo_1/complete") && init?.method === "POST") {
        return jsonResponse(completedTodo);
      }
      if (url.includes("status=all")) {
        return jsonResponse({ items: [completedTodo], total: 1, limit: 200, offset: 0 });
      }
      if (url.startsWith("http://desktop.test/api/user-todos?")) {
        return jsonResponse({ items: [baseTodo], total: 1, limit: 200, offset: 0 });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UserTodoScreen />);

    await screen.findByText("准备会议");
    fireEvent.click(screen.getByRole("button", { name: "标记完成" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/user-todos/utodo_1/complete",
        expect.objectContaining({ method: "POST", body: JSON.stringify({ done: true }) }),
      ),
    );

    fireEvent.click(screen.getByRole("tab", { name: "全部" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("status=all"),
        expect.any(Object),
      ),
    );
  });

  test("shows an inviting empty state when there are no todos", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ items: [], total: 0, limit: 200, offset: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(<UserTodoScreen />);

    await waitFor(() => expect(screen.getByText("还没有待办")).toBeInTheDocument());
    expect(screen.getByText("在上面添加第一件要做的事吧")).toBeInTheDocument();
  });

  test("refreshes when the screen is opened after the store was already hydrated", async () => {
    useUserTodoStore.setState({
      hydrated: true,
      items: [],
      total: 0,
    });
    const addedElsewhere = {
      ...baseTodo,
      todoId: "utodo_from_db",
      title: "数据库新增待办",
    };
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("status=open")) {
        return jsonResponse({ items: [addedElsewhere], total: 1, limit: 200, offset: 0 });
      }
      return jsonResponse({ items: [], total: 0, limit: 1, offset: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UserTodoScreen />);

    await screen.findByText("数据库新增待办");
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("status=open"),
      expect.any(Object),
    );
  });

  test("让 AI 做 button prefills assistant draft and switches route", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.startsWith("http://desktop.test/api/user-todos?")) {
        return jsonResponse({ items: [baseTodo], total: 1, limit: 200, offset: 0 });
      }
      return jsonResponse({ items: [], total: 0, limit: 1, offset: 0 });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<UserTodoScreen />);
    await screen.findByText("准备会议");

    fireEvent.click(screen.getByRole("button", { name: "让 AI 做" }));

    await waitFor(() => {
      const draft = useAssistantStore.getState().draft;
      expect(draft).toContain("准备会议");
      expect(draft).toContain("一次性定时任务");
    });
    expect(useShellStore.getState().activeRoute).toBe("assistant");
    expect(useToastStore.getState().toasts.some((t) => t.message.includes("AI 助手"))).toBe(true);
  });

  test("让 AI 做 prefills description when todo has one", async () => {
    const todoWithDesc = { ...baseTodo, description: "整理议程并发给所有人" };
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/user-todos?")) {
          return jsonResponse({ items: [todoWithDesc], total: 1, limit: 200, offset: 0 });
        }
        return jsonResponse({ items: [], total: 0, limit: 1, offset: 0 });
      }),
    );

    render(<UserTodoScreen />);
    await screen.findByText("准备会议");

    fireEvent.click(screen.getByRole("button", { name: "让 AI 做" }));

    await waitFor(() => {
      const draft = useAssistantStore.getState().draft;
      expect(draft).toContain("整理议程并发给所有人");
    });
  });

  test("shows 上次让 AI 做 outcome when a scheduled task references this todo", async () => {
    useScheduledStore.setState({
      hydrated: true,
      tasks: [
        {
          scheduledTaskId: "sch_1",
          sourceType: "todo",
          sourceRef: "utodo_1",
          title: "准备会议",
          scheduleKind: "one_shot",
          scheduleDescription: "一次性 7月19日 17:00",
          status: "completed",
          unattendedAutoApprove: false,
          nextFireAt: null,
          lastFireAt: "2026-07-19T09:00:00Z",
          lastRunOutcome: "succeeded",
          lastRunAt: "2026-07-19T09:05:00Z",
          createdAt: "2026-07-18T10:00:00Z",
          updatedAt: "2026-07-19T09:05:00Z",
        },
      ],
      tasksTotal: 1,
    });

    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/user-todos?")) {
          return jsonResponse({ items: [baseTodo], total: 1, limit: 200, offset: 0 });
        }
        return jsonResponse({ items: [], total: 0, limit: 1, offset: 0 });
      }),
    );

    render(<UserTodoScreen />);
    await screen.findByText("准备会议");

    // T061：展示上次执行结果，不自动标记完成。
    expect(screen.getByText(/上次让 AI 做/)).toBeInTheDocument();
    expect(screen.getByText(/成功/)).toBeInTheDocument();
    // 待办本身仍处于 pending 状态（不会被调度任务自动改）。
    expect(screen.getByRole("button", { name: "标记完成" })).toBeInTheDocument();
  });

  test("does not show 上次让 AI 做 when no scheduled task references the todo", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.startsWith("http://desktop.test/api/user-todos?")) {
          return jsonResponse({ items: [baseTodo], total: 1, limit: 200, offset: 0 });
        }
        return jsonResponse({ items: [], total: 0, limit: 1, offset: 0 });
      }),
    );

    render(<UserTodoScreen />);
    await screen.findByText("准备会议");

    expect(screen.queryByText(/上次让 AI 做/)).not.toBeInTheDocument();
  });
});
