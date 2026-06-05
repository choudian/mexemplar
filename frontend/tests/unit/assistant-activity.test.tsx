import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import ActivityTimeline from "../../src/screens/assistant/ActivityTimeline";
import SubagentCard from "../../src/screens/assistant/SubagentCard";
import SubagentDetailDrawer from "../../src/screens/assistant/SubagentDetailDrawer";
import { useAssistantStore } from "../../src/state/assistantStore";
import type { ActivityStep, Subagent } from "../../src/state/assistantStore";
import type { UiEvent } from "../../src/api/uiEvents";

function step(partial: Partial<ActivityStep> & { seq: number }): ActivityStep {
  return { kind: "tool_call", text: "x", subagentId: null, ...partial };
}

describe("ActivityTimeline (US3)", () => {
  afterEach(() => vi.unstubAllGlobals());

  test("默认折叠，运行中不自动展开", () => {
    render(<ActivityTimeline sessionId="s1" liveSteps={[step({ seq: 1, toolName: "noop" })]} running />);
    const details = screen.getByText(/正在处理/).closest("details");
    expect(details).not.toHaveAttribute("open");
  });

  test("展开显示实时主步骤（最终回复不在其中，因仅渲染步骤）", () => {
    render(
      <ActivityTimeline
        sessionId="s1"
        liveSteps={[
          step({ seq: 1, kind: "reasoning", text: "想一想", subagentId: null }),
          step({ seq: 2, kind: "tool_call", toolName: "noop", text: "args", subagentId: null }),
        ]}
        running={false}
      />,
    );
    expect(screen.getByText("想一想")).toBeInTheDocument();
    expect(screen.getByText("noop")).toBeInTheDocument();
  });

  test("子任务步骤（subagentId 非空）不进主时间线", () => {
    render(
      <ActivityTimeline
        sessionId="s1"
        liveSteps={[step({ seq: 1, kind: "tool_call", text: "子步骤", subagentId: "c1" })]}
        running={false}
      />,
    );
    expect(screen.queryByText("子步骤")).not.toBeInTheDocument();
  });

  test("历史会话展开经 transcript 重建，已压缩回合显示规整概要提示", async () => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    const fetchMock = vi.fn(async () => ({
      ok: true,
      json: async () => ({ steps: [{ kind: "tool_call", toolName: "hist", text: "y", seq: 1 }], compressed: true }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    render(<ActivityTimeline sessionId="s1" turnId="seq_1" liveSteps={[]} running={false} afterSequence={1} beforeSequence={4} />);
    const details = screen.getByText(/查看这一回合/).closest("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent(details, new Event("toggle", { bubbles: true }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    const firstCall = fetchMock.mock.calls[0] as unknown as [RequestInfo | URL, RequestInit?];
    expect(String(firstCall[0])).toContain("afterSequence=1");
    expect(String(firstCall[0])).toContain("beforeSequence=4");
    expect(await screen.findByText("hist")).toBeInTheDocument();
    expect(screen.getByText(/已折叠为概要/)).toBeInTheDocument();
  });

  test("历史 transcript 拉取失败显示可重试错误，不显示为空步骤", async () => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    let calls = 0;
    const fetchMock = vi.fn(async () => {
      calls += 1;
      if (calls <= 2) {
        throw new Error("network down");
      }
      return {
        ok: true,
        json: async () => ({ steps: [{ kind: "tool_result", toolName: "retry", text: "ok", seq: 1 }], compressed: false }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ActivityTimeline sessionId="s1" turnId="seq_1" liveSteps={[]} running={false} />);
    const details = screen.getByText(/查看这一回合/).closest("details") as HTMLDetailsElement;
    details.open = true;
    fireEvent(details, new Event("toggle", { bubbles: true }));

    expect(await screen.findByRole("alert")).toHaveTextContent("过程加载失败，请重试。");
    expect(screen.queryByText("还没有可展开的过程。")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "重试" }));
    expect(await screen.findByText("retry")).toBeInTheDocument();
  });
});

describe("SubagentCard (US4/US5)", () => {
  test("反映状态，双击与回车均可打开详情（键盘可达）", () => {
    const onOpen = vi.fn();
    const sub: Subagent = { subagentId: "c1", label: "子助手 · 检索", task: "查资料", status: "running" };
    render(<SubagentCard subagent={sub} onOpen={onOpen} />);
    expect(screen.getByText("运行中")).toBeInTheDocument();
    const card = screen.getByRole("button", { name: /子任务/ });
    fireEvent.doubleClick(card);
    fireEvent.keyDown(card, { key: "Enter" });
    expect(onOpen).toHaveBeenCalledTimes(2);
  });

  test("suspended 卡片在提供 onContinue 时显示'继续任务'并可填补充消息", () => {
    const onContinue = vi.fn();
    const sub: Subagent = { subagentId: "c1", label: "x", task: "t", status: "suspended" };
    render(<SubagentCard subagent={sub} onOpen={() => {}} onContinue={onContinue} />);
    fireEvent.click(screen.getByRole("button", { name: "继续任务" }));
    const input = screen.getByLabelText(/补充说明/);
    fireEvent.change(input, { target: { value: "再补一句" } });
    fireEvent.click(screen.getByRole("button", { name: "继续" }));
    expect(onContinue).toHaveBeenCalledWith("再补一句");
  });

  test("继续任务输入框回车只提交续跑，不冒泡打开详情", () => {
    const onOpen = vi.fn();
    const onContinue = vi.fn();
    const sub: Subagent = { subagentId: "c1", label: "x", task: "t", status: "suspended" };
    render(<SubagentCard subagent={sub} onOpen={onOpen} onContinue={onContinue} />);
    fireEvent.click(screen.getByRole("button", { name: "继续任务" }));
    const input = screen.getByLabelText(/补充说明/);
    fireEvent.change(input, { target: { value: "再补一句" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(onContinue).toHaveBeenCalledWith("再补一句");
    expect(onOpen).not.toHaveBeenCalled();
  });

  test("running 卡片不显示'继续任务'", () => {
    const sub: Subagent = { subagentId: "c1", label: "x", task: "t", status: "running" };
    render(<SubagentCard subagent={sub} onOpen={() => {}} onContinue={() => {}} />);
    expect(screen.queryByRole("button", { name: "继续任务" })).not.toBeInTheDocument();
  });

  test("详情 transcript 拉取失败显示可重试错误，不显示为空步骤", async () => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    const fetchMock = vi.fn(async () => {
      throw new Error("network down");
    });
    vi.stubGlobal("fetch", fetchMock);
    const sub: Subagent = { subagentId: "c1", label: "子助手", task: "查资料", status: "suspended" };

    render(<SubagentDetailDrawer sessionId="s1" subagent={sub} onClose={() => {}} />);

    expect(await screen.findByRole("alert")).toHaveTextContent("过程加载失败，请重试。");
    expect(screen.queryByText("还没有步骤。")).not.toBeInTheDocument();
  });
});

function activityEvent(sessionId: string, payload: Record<string, unknown>): UiEvent {
  return {
    eventId: "evt_a",
    sequence: 1,
    sessionId: "ui",
    causationId: null,
    type: "assistant.activity",
    scope: { sessionId },
    payload,
    createdAt: "2026-06-04T00:00:00Z",
  } as UiEvent;
}

function subagentEvent(sessionId: string, payload: Record<string, unknown>): UiEvent {
  return {
    eventId: "evt_s",
    sequence: 2,
    sessionId: "ui",
    causationId: null,
    type: "assistant.subagent",
    scope: { sessionId },
    payload,
    createdAt: "2026-06-04T00:00:00Z",
  } as UiEvent;
}

describe("assistantStore 活动/子任务消费 (US3/US4)", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useAssistantStore.setState({
      activeSessionId: "s1",
      messages: [{ sequence: 1, role: "user", content: "做事", createdAt: null, rendering: "plain_text" }],
      pendingOptimisticMessages: [],
      turnActivityBySession: {
        s1: { seq_1: { turnId: "seq_1", fromSequence: 1, steps: [], subagents: [] } },
      },
      activeTurnIdBySession: { s1: "seq_1" },
    });
  });
  afterEach(() => vi.unstubAllGlobals());

  test("消费 assistant.activity 追加主步骤；assistant.subagent upsert 同一卡片", () => {
    const store = useAssistantStore.getState();
    store.applyEvent(activityEvent("s1", { seq: 1, kind: "tool_call", toolName: "noop", text: "x", subagentId: null }));
    expect(useAssistantStore.getState().turnActivityBySession.s1.seq_1.steps).toHaveLength(1);

    store.applyEvent(subagentEvent("s1", { subagentId: "c1", label: "子助手", task: "查", status: "running" }));
    store.applyEvent(subagentEvent("s1", { subagentId: "c1", status: "done" }));
    const cards = useAssistantStore.getState().turnActivityBySession.s1.seq_1.subagents;
    expect(cards).toHaveLength(1);
    expect(cards[0].status).toBe("done");
    expect(cards[0].label).toBe("子助手"); // 保留先前字段
  });

  test("continueSubagent 经 sendAssistantMessage 发带 subagentId + 补充的续跑指令 (US5)", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ accepted: true, sessionId: "s1" }) }));
    vi.stubGlobal("fetch", fetchMock);
    await act(async () => {
      await useAssistantStore.getState().continueSubagent("s1", "c1", "再补一句");
    });
    const call = (fetchMock.mock.calls as unknown as Array<[RequestInfo | URL, RequestInit?]>)
      .find((c) => String(c[0]).endsWith("/api/assistant/sessions/s1/messages"));
    expect(call).toBeDefined();
    const body = JSON.parse((call![1] as RequestInit).body as string);
    expect(body.content).not.toContain("c1");
    expect(body.content).toContain("再补一句");
    expect(body.continueSubagent).toEqual({ subagentId: "c1", supplemental: "再补一句" });
    expect(useAssistantStore.getState().progress.status).toBe("running");
  });

  test("continueSubagent accepted=false 保持 running 门控并移除乐观消息", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, json: async () => ({ accepted: false, sessionId: "s1" }) }));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      await useAssistantStore.getState().continueSubagent("s1", "c1");
    });

    expect(useAssistantStore.getState().pendingOptimisticMessages).toEqual([]);
    expect(useAssistantStore.getState().progress.status).toBe("running");
  });

  test("不同回合的活动步骤按 turn 归属，不混进同一时间线", () => {
    useAssistantStore.setState({
      messages: [
        { sequence: 1, role: "user", content: "第一轮", createdAt: null, rendering: "plain_text" },
        { sequence: 2, role: "assistant", content: "好", createdAt: null, rendering: "safe_markdown" },
        { sequence: 3, role: "user", content: "第二轮", createdAt: null, rendering: "plain_text" },
      ],
      turnActivityBySession: {
        s1: {
          seq_1: { turnId: "seq_1", fromSequence: 1, beforeSequence: 3, steps: [], subagents: [] },
          seq_3: { turnId: "seq_3", fromSequence: 3, steps: [], subagents: [] },
        },
      },
      activeTurnIdBySession: { s1: "seq_1" },
    });

    const store = useAssistantStore.getState();
    store.applyEvent(activityEvent("s1", { seq: 1, kind: "tool_call", text: "第一轮步骤" }));
    useAssistantStore.setState({ activeTurnIdBySession: { s1: "seq_3" } });
    store.applyEvent(activityEvent("s1", { seq: 1, kind: "tool_call", text: "第二轮步骤" }));

    expect(useAssistantStore.getState().turnActivityBySession.s1.seq_1.steps[0].text).toBe("第一轮步骤");
    expect(useAssistantStore.getState().turnActivityBySession.s1.seq_3.steps[0].text).toBe("第二轮步骤");
  });

  test("backend.resync_required 同时刷新子任务列表与当前回合 transcript", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/subagents")) {
        return {
          ok: true,
          json: async () => ({
            items: [{ subagentId: "c1", label: "x", task: "t", status: "running", lastOutput: null, turnStartSequence: 1 }],
          }),
        };
      }
      if (url.includes("/transcript")) {
        return {
          ok: true,
          json: async () => ({ steps: [{ kind: "tool_call", toolName: "snapshot", text: "权威步骤", seq: 1 }], compressed: false }),
        };
      }
      return { ok: true, json: async () => ({}) };
    });
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      useAssistantStore.getState().applyEvent({
        eventId: "evt_r",
        sequence: 3,
        sessionId: "ui",
        causationId: null,
        type: "backend.resync_required",
        scope: {},
        payload: { reason: "replay_gap", domains: ["assistant"] },
        createdAt: "2026-06-04T00:00:00Z",
      } as UiEvent);
      await Promise.resolve();
    });

    await waitFor(() => expect(useAssistantStore.getState().turnActivityBySession.s1.seq_1.subagents).toHaveLength(1));
    await waitFor(() => expect(useAssistantStore.getState().turnActivityBySession.s1.seq_1.steps[0].toolName).toBe("snapshot"));
  });

  test("backend.resync_required 刷新失败时暴露错误状态", async () => {
    const fetchMock = vi.fn(async () => ({
      ok: false,
      status: 500,
      text: async () => JSON.stringify({ detail: { error: "internal_error" } }),
    }));
    vi.stubGlobal("fetch", fetchMock);

    await act(async () => {
      useAssistantStore.getState().applyEvent({
        eventId: "evt_r_fail",
        sequence: 4,
        sessionId: "ui",
        causationId: null,
        type: "backend.resync_required",
        scope: {},
        payload: { reason: "replay_gap", domains: ["assistant"] },
        createdAt: "2026-06-04T00:00:00Z",
      } as UiEvent);
      await Promise.resolve();
    });

    await waitFor(() => expect(useAssistantStore.getState().lastError).toMatch(/无法刷新/));
  });
});
