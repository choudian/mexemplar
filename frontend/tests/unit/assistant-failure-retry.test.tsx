import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { AssistantScreen } from "../../src/screens/assistant/AssistantScreen";
import { useAssistantStore } from "../../src/state/assistantStore";

const failure = {
  category: "network" as const,
  message: "连接模型服务时中断了。",
  suggestion: "请检查网络连接后重试。",
  attemptCount: 1,
  failedAt: "2026-06-15T00:00:01Z",
};

const failedMessage = {
  sequence: 1,
  role: "user" as const,
  content: "完成季度报告",
  createdAt: "2026-06-15T00:00:00Z",
  rendering: "plain_text" as const,
  failure,
};

function response(payload: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => payload,
  } as Response;
}

describe("Assistant failed-message recovery", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    window.history.replaceState({}, "", "/");
    useAssistantStore.setState({
      hydrated: true,
      sessions: [
        {
          sessionId: "ast_1",
          title: "失败恢复",
          preview: "完成季度报告",
          status: "active",
          createdAt: null,
          updatedAt: null,
          dateLabel: "今天",
        },
      ],
      activeSessionId: "ast_1",
      messages: [failedMessage],
      query: "",
      draft: "",
      loadingSessions: false,
      loadingMessages: false,
      sending: false,
      stopping: false,
      hasMoreBefore: false,
      nextBeforeSequence: null,
      progress: { status: "failed", headline: failure.message },
      progressBySession: { ast_1: { status: "failed", headline: failure.message } },
      stoppingBySession: {},
      confirmations: [],
      lastError: null,
      pendingOptimisticMessages: [],
      turnActivityBySession: { ast_1: {} },
      activeTurnIdBySession: { ast_1: "seq_1" },
      queuedMessageBySession: {},
      retryingFailureBySession: {},
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.replaceState({}, "", "/");
  });

  test("renders the persisted failure card under its user message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ items: [] })));

    render(<AssistantScreen />);

    expect(await screen.findByText("这条消息没有完成")).toBeInTheDocument();
    expect(screen.getByText(failure.message)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "重试" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "编辑后重试" })).toBeEnabled();
  });

  test("submits one original retry and disables duplicate actions while pending", async () => {
    let resolveRetry!: (value: Response) => void;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/retry") && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolveRetry = resolve;
        });
      }
      return response({ items: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AssistantScreen />);

    const retry = await screen.findByRole("button", { name: "重试" });
    fireEvent.click(retry);
    fireEvent.click(retry);

    expect(await screen.findByRole("button", { name: "处理中" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "查看调试信息" })).toBeDisabled();
    expect(
      fetchMock.mock.calls.filter(([url]) => String(url).endsWith("/api/assistant/sessions/ast_1/retry")),
    ).toHaveLength(1);

    await act(async () => {
      resolveRetry(response({ accepted: true, sessionId: "ast_1", messageSequence: 1 }));
      await Promise.resolve();
    });
  });

  test("restores recovery actions and reports the API error when retry submission fails", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/retry") && init?.method === "POST") {
        throw new Error("desktop bridge unavailable");
      }
      return response({ items: [] });
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<AssistantScreen />);

    fireEvent.click(await screen.findByRole("button", { name: "重试" }));

    await waitFor(() => expect(screen.getByRole("button", { name: "重试" })).toBeEnabled());
    expect(screen.getByRole("button", { name: "查看调试信息" })).toBeEnabled();
    expect(useAssistantStore.getState().retryingFailureBySession).toEqual({});
    expect(useAssistantStore.getState().lastError).toBe("desktop bridge unavailable");
  });

  test("supports edit, cancel, and edited retry without mutating the old bubble", async () => {
    const fetchMock = vi.fn(async () =>
      response({ accepted: true, sessionId: "ast_1", messageSequence: 1 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    render(<AssistantScreen />);

    fireEvent.click(await screen.findByRole("button", { name: "编辑后重试" }));
    const editor = screen.getByLabelText("编辑后重试");
    fireEvent.change(editor, { target: { value: "缩小范围后重新完成报告" } });
    fireEvent.click(screen.getByRole("button", { name: "取消" }));
    expect(screen.queryByLabelText("编辑后重试")).not.toBeInTheDocument();
    expect(screen.getByText("完成季度报告")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "编辑后重试" }));
    fireEvent.change(screen.getByLabelText("编辑后重试"), {
      target: { value: "缩小范围后重新完成报告" },
    });
    fireEvent.click(screen.getByRole("button", { name: "提交重试" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/assistant/sessions/ast_1/retry",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({
            messageSequence: 1,
            content: "缩小范围后重新完成报告",
          }),
        }),
      ),
    );
  });

  test("authoritative events remove the old card and move a repeated failure to the new message", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ items: [] })));
    render(<AssistantScreen />);
    await screen.findByText("这条消息没有完成");

    act(() => {
      useAssistantStore.getState().applyEvent({
        eventId: "evt_clear",
        sequence: 1,
        sessionId: "ui_1",
        type: "assistant.message",
        scope: { sessionId: "ast_1" },
        payload: { ...failedMessage, failure: undefined },
        createdAt: "2026-06-15T00:00:02Z",
      });
      useAssistantStore.getState().applyEvent({
        eventId: "evt_new",
        sequence: 2,
        sessionId: "ui_1",
        type: "assistant.message",
        scope: { sessionId: "ast_1" },
        payload: {
          ...failedMessage,
          sequence: 2,
          content: "缩小范围后重新完成报告",
          failure: { ...failure, attemptCount: 2 },
        },
        createdAt: "2026-06-15T00:00:03Z",
      });
    });

    expect(screen.getAllByText("这条消息没有完成")).toHaveLength(1);
    expect(screen.getByText("第 2 次尝试")).toBeInTheDocument();
    expect(useAssistantStore.getState().lastError).toBeNull();

    act(() => {
      useAssistantStore.getState().applyEvent({
        eventId: "evt_failed",
        sequence: 3,
        sessionId: "ui_1",
        type: "assistant.progress",
        scope: { sessionId: "ast_1" },
        payload: { status: "failed", headline: failure.message },
        createdAt: "2026-06-15T00:00:04Z",
      });
    });
    expect(useAssistantStore.getState().lastError).toBeNull();
  });

  test("debug action navigates with the owning session id", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => response({ items: [] })));
    render(<AssistantScreen />);

    fireEvent.click(await screen.findByRole("button", { name: "查看调试信息" }));

    expect(window.location.pathname).toBe("/debug");
    expect(new URLSearchParams(window.location.search).get("sessionId")).toBe("ast_1");
  });
});
