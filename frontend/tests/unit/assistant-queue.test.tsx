import { act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { useAssistantStore } from "../../src/state/assistantStore";
import type { UiEvent } from "../../src/api/uiEvents";

function progressEvent(status: string, sessionId = "ast_1"): UiEvent {
  return {
    eventId: `evt_${status}`,
    sequence: 1,
    sessionId: "ui_sess_test",
    causationId: null,
    type: "assistant.progress",
    scope: { sessionId },
    payload: { status, headline: "" },
    createdAt: "2026-06-04T00:00:00Z",
  } as UiEvent;
}

describe("assistantStore 排队状态机 (US2)", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useAssistantStore.setState({
      activeSessionId: "ast_1",
      draft: "",
      draftBySession: {},
      progress: { status: "running", headline: "" },
      progressBySession: { ast_1: { status: "running", headline: "" } },
      stoppingBySession: {},
      queuedMessageBySession: {},
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("三态：输入→editing，回车/失焦→queued，双击→editing；每会话仅一条", () => {
    const store = useAssistantStore.getState();
    store.setQueuedText("下一步");
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1).toEqual({
      text: "下一步",
      state: "editing",
    });
    // 再写改同一条（单条不变量）
    store.setQueuedText("下一步，再补一句");
    expect(Object.keys(useAssistantStore.getState().queuedMessageBySession)).toEqual(["ast_1"]);

    store.commitQueued();
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1.state).toBe("queued");

    store.editQueued();
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1.state).toBe("editing");
  });

  test("succeeded：已 queued 自动派发并清空排队", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ accepted: true, sessionId: "ast_1" }) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({ queuedMessageBySession: { ast_1: { text: "排队内容", state: "queued" } } });

    await act(async () => {
      useAssistantStore.getState().applyEvent(progressEvent("succeeded"));
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/assistant/sessions/ast_1/messages",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ content: "排队内容" }) }),
    );
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1).toBeUndefined();
  });

  test("waiting_for_user：已 queued 也自动派发（对反问的回应）", () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ accepted: true, sessionId: "ast_1" }) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({ queuedMessageBySession: { ast_1: { text: "回应反问", state: "queued" } } });

    act(() => {
      useAssistantStore.getState().applyEvent(progressEvent("waiting_for_user"));
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  test("编辑态：succeeded 也不外发，退回普通草稿（0 例提前外发）", () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({ queuedMessageBySession: { ast_1: { text: "编辑中", state: "editing" } } });

    act(() => {
      useAssistantStore.getState().applyEvent(progressEvent("succeeded"));
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(useAssistantStore.getState().draft).toBe("编辑中");
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1).toBeUndefined();
  });

  test("cancelled：排队退回普通草稿、不派发", () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({ queuedMessageBySession: { ast_1: { text: "停止前排的", state: "queued" } } });

    act(() => {
      useAssistantStore.getState().applyEvent(progressEvent("cancelled"));
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(useAssistantStore.getState().draft).toBe("停止前排的");
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1).toBeUndefined();
  });

  test("failed：排队退回普通草稿、不派发", () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({ queuedMessageBySession: { ast_1: { text: "失败前排的", state: "queued" } } });

    act(() => {
      useAssistantStore.getState().applyEvent(progressEvent("failed"));
    });

    expect(fetchMock).not.toHaveBeenCalled();
    expect(useAssistantStore.getState().draft).toBe("失败前排的");
  });

  test("按 sessionId 各存一份、跨会话切换保留", () => {
    const store = useAssistantStore.getState();
    store.setQueuedText("ast_1 的排队");
    // 切到另一个会话（仅改 activeSessionId，模拟切换）
    useAssistantStore.setState({ activeSessionId: "ast_2" });
    store.setQueuedText("ast_2 的排队");
    const map = useAssistantStore.getState().queuedMessageBySession;
    expect(map.ast_1.text).toBe("ast_1 的排队");
    expect(map.ast_2.text).toBe("ast_2 的排队");
    // 切回 ast_1 仍在
    useAssistantStore.setState({ activeSessionId: "ast_1" });
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1.text).toBe("ast_1 的排队");
  });

  test("非当前会话完成时按该 session 自动派发排队消息，不覆盖当前草稿", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ accepted: true, sessionId: "ast_1" }) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({
      activeSessionId: "ast_2",
      draft: "ast_2 草稿",
      draftBySession: { ast_2: "ast_2 草稿" },
      progress: { status: "idle", headline: "" },
      progressBySession: { ast_1: { status: "running", headline: "" }, ast_2: { status: "idle", headline: "" } },
      queuedMessageBySession: { ast_1: { text: "ast_1 排队", state: "queued" } },
    });

    await act(async () => {
      useAssistantStore.getState().applyEvent(progressEvent("succeeded", "ast_1"));
      await Promise.resolve();
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/assistant/sessions/ast_1/messages",
      expect.objectContaining({ method: "POST", body: JSON.stringify({ content: "ast_1 排队" }) }),
    );
    expect(useAssistantStore.getState().draft).toBe("ast_2 草稿");
    expect(useAssistantStore.getState().progress.status).toBe("idle");
    expect(useAssistantStore.getState().queuedMessageBySession.ast_1).toBeUndefined();
  });

  test("并发安全网：自动派发撞 accepted=false 静默重排为 queued", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ accepted: false, sessionId: "ast_1" }) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({ queuedMessageBySession: { ast_1: { text: "重排内容", state: "queued" } } });

    await act(async () => {
      useAssistantStore.getState().applyEvent(progressEvent("succeeded"));
      await Promise.resolve();
      await Promise.resolve();
    });

    expect(useAssistantStore.getState().queuedMessageBySession.ast_1).toEqual({
      text: "重排内容",
      state: "queued",
    });
  });
});
