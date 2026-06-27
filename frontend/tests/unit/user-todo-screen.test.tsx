import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { UserTodoScreen } from "../../src/screens/UserTodoScreen/UserTodoScreen";
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
});
