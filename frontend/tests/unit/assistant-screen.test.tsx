import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { AssistantScreen } from "../../src/screens/assistant/AssistantScreen";
import { useAssistantStore } from "../../src/state/assistantStore";
import { useAssistantTaskStore } from "../../src/state/assistantTaskStore";
import type { AssistantTaskGraphSnapshot } from "../../src/api/assistantTasks";

const sessionsPayload = {
  items: [
    {
      sessionId: "ast_1",
      title: "Budget review",
      preview: "Summarize the spend",
      status: "active",
      createdAt: "2026-05-10T00:00:00Z",
      updatedAt: "2026-05-10T00:00:00Z",
      dateLabel: "2026-05-10",
    },
  ],
};

const messagesPayload = {
  items: [
    {
      sequence: 1,
      role: "user",
      content: "Summarize the spend",
      createdAt: "2026-05-10T00:00:00Z",
      rendering: "plain_text",
    },
    {
      sequence: 2,
      role: "assistant",
      content: "### Summary\n- No raw <script> HTML is rendered.",
      createdAt: "2026-05-10T00:00:01Z",
      rendering: "safe_markdown",
    },
  ],
  hasMoreBefore: false,
  nextBeforeSequence: 1,
};

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

describe("AssistantScreen", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useAssistantStore.setState({
      hydrated: false,
      sessions: [],
      activeSessionId: null,
      messages: [],
      query: "",
      draft: "",
      loadingSessions: false,
      loadingMessages: false,
      sending: false,
      hasMoreBefore: false,
      nextBeforeSequence: null,
      progress: { status: "idle", headline: "" },
      confirmations: [],
      lastError: null,
      pendingOptimisticMessages: [],
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("loads sessions, selects a conversation, and sends a message", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions?limit=200")) {
        return jsonResponse(sessionsPayload);
      }
      if (url.includes("/api/assistant/sessions/ast_1/messages?limit=10")) {
        return jsonResponse(messagesPayload);
      }
      if (url.endsWith("/api/assistant/sessions/ast_1/messages") && init?.method === "POST") {
        return jsonResponse({ accepted: true, sessionId: "ast_1" });
      }
      return jsonResponse({ items: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<AssistantScreen />);

    await waitFor(() => expect(screen.getByText("Budget review")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Budget review/ }));

    await waitFor(() => expect(screen.getByText("Summary")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("输入消息"), { target: { value: "Continue" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/assistant/sessions/ast_1/messages",
        expect.objectContaining({
          method: "POST",
          body: JSON.stringify({ content: "Continue" }),
        }),
      );
    });
  });

  test("renders high-risk confirmation independently from the composer", async () => {
    const fetchMock = vi.fn(async () => jsonResponse({ requestId: "req_1", decision: "deny", accepted: true }));
    vi.stubGlobal("fetch", fetchMock);

    render(<AssistantScreen />);
    act(() => {
      useAssistantStore.getState().applyEvent({
        eventId: "evt_1",
        sequence: 1,
        sessionId: "ui_sess_test",
        causationId: "ast_1",
        type: "assistant.confirmation",
        scope: {},
        payload: {
          requestId: "req_1",
          actionType: "exec",
          sanitizedSummary: "命令首行: npm test",
          status: "active",
        },
        createdAt: "2026-05-10T00:00:00Z",
      });
    });

    expect(await screen.findByRole("alert")).toHaveTextContent("命令首行: npm test");
    fireEvent.click(screen.getByRole("button", { name: "拒绝" }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/assistant/confirmations/req_1/decision",
        expect.objectContaining({ method: "POST" }),
      );
    });
  });

  test("removes optimistic message when backend rejects concurrent send", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/messages") && init?.method === "POST") {
        return jsonResponse({ accepted: false, sessionId: "ast_1" });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({
      activeSessionId: "ast_1",
      draft: "Second message",
      messages: [],
      sending: false,
      progress: { status: "idle", headline: "" },
      pendingOptimisticMessages: [],
    });

    await act(async () => {
      await useAssistantStore.getState().sendDraft();
    });

    expect(useAssistantStore.getState().messages).toEqual([]);
    expect(useAssistantStore.getState().draft).toBe("Second message");
    expect(useAssistantStore.getState().pendingOptimisticMessages).toEqual([]);
    expect(useAssistantStore.getState().progress.status).toBe("running");
  });

  test("keeps authoritative assistant reply when a later optimistic send is rejected", async () => {
    let resolvePost!: (response: Response) => void;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/messages") && init?.method === "POST") {
        return new Promise<Response>((resolve) => {
          resolvePost = resolve;
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({
      activeSessionId: "ast_1",
      draft: "Second question",
      messages: [
        {
          sequence: 1,
          role: "user",
          content: "First question",
          createdAt: "2026-05-10T00:00:00Z",
          rendering: "plain_text",
        },
      ],
      sending: false,
      progress: { status: "idle", headline: "" },
      pendingOptimisticMessages: [],
    });

    let sendPromise!: Promise<void>;
    await act(async () => {
      sendPromise = useAssistantStore.getState().sendDraft();
      await Promise.resolve();
    });

    expect(useAssistantStore.getState().pendingOptimisticMessages).toMatchObject([
      { content: "Second question", sessionId: "ast_1" },
    ]);

    act(() => {
      useAssistantStore.getState().applyEvent({
        eventId: "evt_a1",
        sequence: 2,
        sessionId: "ui_sess_test",
        causationId: "ast_1",
        type: "assistant.message",
        scope: { sessionId: "ast_1" },
        payload: {
          sequence: 2,
          role: "assistant",
          content: "First answer",
          createdAt: "2026-05-10T00:00:01Z",
          rendering: "safe_markdown",
        },
        createdAt: "2026-05-10T00:00:01Z",
      });
    });

    expect(useAssistantStore.getState().messages.map((message) => message.content)).toEqual([
      "First question",
      "First answer",
    ]);
    expect(useAssistantStore.getState().pendingOptimisticMessages).toMatchObject([
      { content: "Second question", sessionId: "ast_1" },
    ]);

    await act(async () => {
      resolvePost(jsonResponse({ accepted: false, sessionId: "ast_1" }) as Response);
      await sendPromise;
    });

    expect(useAssistantStore.getState().messages.map((message) => message.content)).toEqual([
      "First question",
      "First answer",
    ]);
    expect(useAssistantStore.getState().draft).toBe("Second question");
    expect(useAssistantStore.getState().pendingOptimisticMessages).toEqual([]);
    expect(useAssistantStore.getState().progress.status).toBe("running");
  });

  test("sends the exact draft without trimming leading or trailing whitespace", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/messages") && init?.method === "POST") {
        return jsonResponse({ accepted: true, sessionId: "ast_1" });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({
      activeSessionId: "ast_1",
      draft: "  keep me exact\n",
      messages: [],
      sending: false,
      progress: { status: "idle", headline: "" },
      pendingOptimisticMessages: [],
    });

    await act(async () => {
      await useAssistantStore.getState().sendDraft();
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/assistant/sessions/ast_1/messages",
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ content: "  keep me exact\n" }),
      }),
    );
  });

  test("过程时间线渲染在用户消息之后、助理回复之前", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => jsonResponse({ items: [] })));
    useAssistantStore.setState({
      activeSessionId: "ast_1",
      messages: [
        { sequence: 1, role: "user", content: "做事", createdAt: null, rendering: "plain_text" },
        { sequence: 2, role: "assistant", content: "好的", createdAt: null, rendering: "safe_markdown" },
      ],
      turnActivityBySession: {
        ast_1: {
          seq_1: {
            turnId: "seq_1",
            fromSequence: 1,
            steps: [{ seq: 1, kind: "tool_call", toolName: "noop", text: "x", subagentId: null }],
            subagents: [],
          },
        },
      },
      activeTurnIdBySession: { ast_1: "seq_1" },
      progress: { status: "idle", headline: "" },
      pendingOptimisticMessages: [],
    });

    const { container } = render(<AssistantScreen />);
    await waitFor(() => {
      const thread = container.querySelector(".assistant-thread") as HTMLElement;
      const order = Array.from(thread.children);
      const userIdx = order.findIndex((el) => el.matches(".assistant-message[data-role='user']"));
      const activityIdx = order.findIndex((el) => el.matches(".assistant-activity"));
      const assistantIdx = order.findIndex((el) => el.matches(".assistant-message[data-role='assistant']"));
      expect(userIdx).toBeGreaterThanOrEqual(0);
      expect(activityIdx).toBeGreaterThan(userIdx);
      expect(assistantIdx).toBeGreaterThan(activityIdx);
    });
  });

  test("点新对话不创建会话，输入并发送才惰性创建", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions?limit=200")) {
        return jsonResponse(sessionsPayload);
      }
      if (url.endsWith("/api/assistant/sessions") && init?.method === "POST") {
        return jsonResponse({ sessionId: "ast_new" });
      }
      if (url.endsWith("/api/assistant/sessions/ast_new/messages") && init?.method === "POST") {
        return jsonResponse({ accepted: true, sessionId: "ast_new" });
      }
      return jsonResponse({ items: [] });
    });
    vi.stubGlobal("fetch", fetchMock);

    const sessionPosts = () =>
      fetchMock.mock.calls.filter(
        ([u, i]) =>
          String(u).endsWith("/api/assistant/sessions") &&
          (i as RequestInit | undefined)?.method === "POST",
      ).length;

    render(<AssistantScreen />);
    await waitFor(() => expect(screen.getByText("Budget review")).toBeInTheDocument());

    // 点"新对话"：仅切到空白态，不创建后端会话
    fireEvent.click(screen.getByRole("button", { name: "新对话" }));
    await waitFor(() => expect(screen.getByRole("heading", { name: /今天想完成什么/ })).toBeInTheDocument());
    expect(sessionPosts()).toBe(0);

    // 输入并发送 → 惰性创建会话，再把消息发到新会话
    fireEvent.change(screen.getByLabelText("输入消息"), { target: { value: "hello" } });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    await waitFor(() => expect(sessionPosts()).toBe(1));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        "http://desktop.test/api/assistant/sessions/ast_new/messages",
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});

function makeGraphForAnchor(
  userMessageSequence: number | null,
): AssistantTaskGraphSnapshot {
  return {
    graphId: "graph-001",
    sessionId: "ast_1",
    userMessageSequence,
    version: 1,
    tasks: [
      {
        taskId: "tsk-root",
        graphId: "graph-001",
        parentTaskId: null,
        title: "根任务",
        descriptionPreview: "",
        status: "running",
        displayPhase: "running",
        requiresReview: false,
        requiresConfirmation: false,
        safeExplanation: "",
      },
      {
        taskId: "tsk-001",
        graphId: "graph-001",
        parentTaskId: "tsk-root",
        title: "DAG步骤",
        descriptionPreview: "",
        status: "running",
        displayPhase: "running",
        requiresReview: false,
        requiresConfirmation: false,
        safeExplanation: "",
      },
    ],
    edges: [],
    adjudications: [],
  };
}

describe("AssistantScreen taskGraph 锚定", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useAssistantStore.setState({
      hydrated: true,
      sessions: [],
      activeSessionId: "ast_1",
      messages: [
        { sequence: 1, role: "user", content: "第一轮", createdAt: null, rendering: "plain_text" },
        { sequence: 2, role: "assistant", content: "回复一", createdAt: null, rendering: "safe_markdown" },
        { sequence: 3, role: "user", content: "第二轮", createdAt: null, rendering: "plain_text" },
        { sequence: 4, role: "assistant", content: "回复二", createdAt: null, rendering: "safe_markdown" },
      ],
      turnActivityBySession: {
        ast_1: {
          seq_1: {
            turnId: "seq_1",
            fromSequence: 1,
            steps: [{ seq: 1, kind: "reasoning", text: "思考", subagentId: null }],
            subagents: [],
          },
          seq_3: {
            turnId: "seq_3",
            fromSequence: 3,
            steps: [{ seq: 3, kind: "reasoning", text: "思考", subagentId: null }],
            subagents: [],
          },
        },
      },
      activeTurnIdBySession: { ast_1: "seq_3" },
      query: "",
      draft: "",
      loadingSessions: false,
      loadingMessages: false,
      sending: false,
      hasMoreBefore: false,
      nextBeforeSequence: null,
      progress: { status: "idle", headline: "" },
      confirmations: [],
      lastError: null,
      pendingOptimisticMessages: [],
    });
    useAssistantTaskStore.setState({
      currentGraph: null,
      boardItems: [],
      activeMeeting: null,
      todosByTaskId: {},
      todoLoadingTaskIds: [],
      graphLoading: false,
      boardLoading: false,
      meetingLoading: false,
      graphError: null,
      boardError: null,
      meetingError: null,
      needsResync: false,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function stubGraph(graph: AssistantTaskGraphSnapshot) {
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/task-graphs/current")) {
        return jsonResponse({ graph });
      }
      return jsonResponse({ items: [] });
    }));
  }

  test("userMessageSequence 精确匹配 turn → DAG 节点只在该 turn 渲染", async () => {
    stubGraph(makeGraphForAnchor(3));
    const { container } = render(<AssistantScreen />);
    await waitFor(() => {
      expect(container.querySelector(".assistant-task-node")).not.toBeNull();
    });
    const activity1 = container.querySelector('.assistant-activity[data-turn-id="seq_1"]');
    const activity3 = container.querySelector('.assistant-activity[data-turn-id="seq_3"]');
    expect(activity3?.querySelector(".assistant-task-node")).not.toBeNull();
    expect(activity1?.querySelector(".assistant-task-node")).toBeNull();
  });

  test("userMessageSequence 为 null → 回退到最近 turn，DAG 节点不消失", async () => {
    stubGraph(makeGraphForAnchor(null));
    const { container } = render(<AssistantScreen />);
    await waitFor(() => {
      expect(container.querySelector(".assistant-task-node")).not.toBeNull();
    });
    const activity1 = container.querySelector('.assistant-activity[data-turn-id="seq_1"]');
    const activity3 = container.querySelector('.assistant-activity[data-turn-id="seq_3"]');
    expect(activity3?.querySelector(".assistant-task-node")).not.toBeNull();
    expect(activity1?.querySelector(".assistant-task-node")).toBeNull();
  });

  test("origin turn 不在当前窗口 → 回退到最近 turn，DAG 节点不消失", async () => {
    stubGraph(makeGraphForAnchor(99));
    const { container } = render(<AssistantScreen />);
    await waitFor(() => {
      expect(container.querySelector(".assistant-task-node")).not.toBeNull();
    });
    const activity3 = container.querySelector('.assistant-activity[data-turn-id="seq_3"]');
    expect(activity3?.querySelector(".assistant-task-node")).not.toBeNull();
  });
});
