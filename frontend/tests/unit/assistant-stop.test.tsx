import type { ComponentProps } from "react";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import MessageComposer from "../../src/screens/assistant/MessageComposer";
import type { QueuedMessage } from "../../src/state/assistantStore";
import { useAssistantStore } from "../../src/state/assistantStore";

const noop = () => {};

function renderComposer(overrides: Partial<ComponentProps<typeof MessageComposer>> = {}) {
  const props: ComponentProps<typeof MessageComposer> = {
    draft: "",
    sending: false,
    autoApprove: false,
    isRunning: false,
    stopping: false,
    queued: undefined as QueuedMessage | undefined,
    onDraftChange: noop,
    onSend: noop,
    onStop: noop,
    onQueuedTextChange: noop,
    onCommitQueued: noop,
    onEditQueued: noop,
    onToggleAutoApprove: noop,
    ...overrides,
  };
  return render(<MessageComposer {...props} />);
}

describe("MessageComposer 运行时门控与停止 (US1)", () => {
  test("running 时显示停止按钮，点击触发 onStop；回车门控为排队、不发送", () => {
    const onSend = vi.fn();
    const onStop = vi.fn();
    const onCommitQueued = vi.fn();
    renderComposer({ isRunning: true, onSend, onStop, onCommitQueued });
    fireEvent.click(screen.getByRole("button", { name: "停止" }));
    expect(onStop).toHaveBeenCalledTimes(1);
    fireEvent.keyDown(screen.getByLabelText("排队下一条消息"), { key: "Enter" });
    expect(onSend).not.toHaveBeenCalled();
    expect(onCommitQueued).toHaveBeenCalledTimes(1);
  });

  test("stopping 时停止按钮显示'停止中'反馈", () => {
    renderComposer({ isRunning: true, stopping: true });
    expect(screen.getByRole("button", { name: "停止" })).toHaveTextContent("停止中");
  });

  test("waiting_for_user(非 running) 显示发送、输入可用", () => {
    const onSend = vi.fn();
    renderComposer({ draft: "hello", isRunning: false, onSend });
    fireEvent.click(screen.getByRole("button", { name: "发送" }));
    expect(onSend).toHaveBeenCalledTimes(1);
  });
});

describe("assistantStore stopRun (US1)", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    // 共享 zustand 单例：显式清空 per-session map，避免上一个用例残留的
    // stoppingBySession/progressBySession 泄漏导致 stopRun 守卫提前返回。
    useAssistantStore.setState({
      activeSessionId: "ast_1",
      stopping: false,
      stoppingBySession: {},
      progress: { status: "running", headline: "" },
      progressBySession: {},
      lastError: null,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("stopRun 调停止端点、立即置 stopping、生效前重复点击幂等", async () => {
    let resolveStop!: (response: unknown) => void;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/stop") && init?.method === "POST") {
        return new Promise((resolve) => {
          resolveStop = resolve;
        });
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);

    let pending!: Promise<void>;
    await act(async () => {
      pending = useAssistantStore.getState().stopRun();
      await Promise.resolve();
    });
    // 立即进入"停止中"过渡态（≤200ms 同步反馈）
    expect(useAssistantStore.getState().stopping).toBe(true);

    // 生效前重复点击幂等：不再发第二个请求、不报错
    await act(async () => {
      await useAssistantStore.getState().stopRun();
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      resolveStop({ ok: true, json: async () => ({ accepted: true }) });
      await pending;
    });
  });

  test("stopRun 带当前 runId，避免迟到旧停止误停新回合", async () => {
    let stopBody: unknown;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/stop") && init?.method === "POST") {
        stopBody = init.body ? JSON.parse(String(init.body)) : null;
        return { ok: true, json: async () => ({ accepted: true }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({
      progress: { status: "running", headline: "", runId: "run-42" },
      stopping: false,
    });

    await act(async () => {
      await useAssistantStore.getState().stopRun();
    });

    expect(stopBody).toEqual({ runId: "run-42" });
  });

  test("收到 cancelled 进度 → 解锁 stopping、回'已停止'就绪态", () => {
    useAssistantStore.setState({ stopping: true });
    act(() => {
      useAssistantStore.getState().applyEvent({
        eventId: "e1",
        sequence: 9,
        sessionId: "ui_sess_test",
        causationId: null,
        type: "assistant.progress",
        scope: { sessionId: "ast_1" },
        payload: { status: "cancelled", headline: "已停止" },
        createdAt: "2026-06-04T00:00:00Z",
      });
    });
    expect(useAssistantStore.getState().stopping).toBe(false);
    expect(useAssistantStore.getState().progress.status).toBe("cancelled");
  });

  test("仅 running 可停止：非 running 时 stopRun 无操作", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({}) }));
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({ progress: { status: "waiting_for_user", headline: "" }, stopping: false });
    await act(async () => {
      await useAssistantStore.getState().stopRun();
    });
    expect(fetchMock).not.toHaveBeenCalled();
    expect(useAssistantStore.getState().stopping).toBe(false);
  });

  test("stopRun 收到 accepted=false 时清 stopping、提示并刷新权威状态", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith("/api/assistant/sessions/ast_1/stop") && init?.method === "POST") {
        return { ok: true, json: async () => ({ accepted: false }) };
      }
      if (url.includes("/subagents")) {
        return { ok: true, json: async () => ({ items: [] }) };
      }
      if (url.includes("/transcript")) {
        return { ok: true, json: async () => ({ steps: [], compressed: false }) };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);
    useAssistantStore.setState({
      messages: [{ sequence: 1, role: "user", content: "做事", createdAt: null, rendering: "plain_text" }],
      activeTurnIdBySession: { ast_1: "seq_1" },
      turnActivityBySession: {
        ast_1: { seq_1: { turnId: "seq_1", fromSequence: 1, steps: [], subagents: [] } },
      },
    });

    await act(async () => {
      await useAssistantStore.getState().stopRun();
      await Promise.resolve();
    });

    expect(useAssistantStore.getState().stopping).toBe(false);
    expect(useAssistantStore.getState().progress.status).toBe("idle");
    expect(useAssistantStore.getState().lastError).toBe("当前没有正在处理的请求。");
    expect(fetchMock).toHaveBeenCalledWith(
      "http://desktop.test/api/assistant/sessions/ast_1/subagents",
      expect.any(Object),
    );
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining("/api/assistant/sessions/ast_1/transcript"),
      expect.any(Object),
    );
  });
});
