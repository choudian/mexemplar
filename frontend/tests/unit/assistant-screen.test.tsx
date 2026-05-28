import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { AssistantScreen } from "../../src/screens/assistant/AssistantScreen";
import { useAssistantStore } from "../../src/state/assistantStore";

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
    expect(useAssistantStore.getState().progress.status).toBe("waiting_for_user");
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
    expect(useAssistantStore.getState().progress.status).toBe("waiting_for_user");
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
});
