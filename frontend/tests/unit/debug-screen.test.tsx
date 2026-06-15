import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, test, vi } from "vitest";

import DebugScreen from "../../src/screens/debug/DebugScreen";
import * as debugApi from "../../src/api/debug";

vi.mock("../../src/api/debug", () => {
  return {
    DEBUG_RAW_STATE_PURGE_EVENT: "mexemplar:debug-raw-state-purge",
    dispatchDebugControlStatus: vi.fn(),
    getControlStatus: vi.fn(),
    updateControl: vi.fn(),
    listTraces: vi.fn(),
    getTraceDetail: vi.fn(),
    clearTraces: vi.fn(),
    listFlows: vi.fn(),
    getFlowDetail: vi.fn(),
    expandReference: vi.fn(),
  };
});

const disabledStatus = {
  enabled: false,
  armedAt: null,
  retentionEpoch: null,
  warning: "调试记录可能包含原始用户文本",
  limits: { maxRecords: 200, maxRecordBytes: 1024, maxTotalBytes: 4096 },
};

const enabledStatus = {
  ...disabledStatus,
  enabled: true,
  armedAt: "2026-05-24T00:00:00Z",
  retentionEpoch: "epoch_1",
};

const trace = {
  traceId: "trace_done",
  method: "chat",
  source: "agent_loop",
  agentType: "assistant",
  sessionId: "ast_1",
  workflowId: "wf_1",
  workUnitId: null,
  iteration: 1,
  outcome: "succeeded",
  detailAvailability: "full_text",
  retainedBytes: 128,
  createdAt: "2026-05-24T00:00:00Z",
  completedAt: "2026-05-24T00:00:01Z",
  summary: "text_chars:12",
  linkedTransitionIds: ["tr_1"],
};

describe("DebugScreen", () => {
  beforeEach(() => {
    vi.mocked(debugApi.getControlStatus).mockReset().mockResolvedValue(disabledStatus);
    vi.mocked(debugApi.updateControl).mockReset().mockResolvedValue(enabledStatus);
    vi.mocked(debugApi.listTraces).mockReset().mockResolvedValue({
      items: [trace],
      retainedBytes: 128,
      omittedCount: 0,
      warning: "armed",
    });
    vi.mocked(debugApi.getTraceDetail).mockReset().mockResolvedValue({
      ...trace,
      inputMessages: [{ role: "user", content: "safe prompt" }],
      inputMedia: [],
      inputTools: null,
      outputContent: "safe answer",
      outputToolCalls: [],
      errorSummary: null,
    });
    vi.mocked(debugApi.clearTraces).mockReset().mockResolvedValue(undefined);
    vi.mocked(debugApi.listFlows).mockReset().mockResolvedValue({
      items: [
        {
          workflowId: "wf_1",
          transitionCount: 2,
          lastEventType: "assistant_delegation_completed",
          lastCreatedAt: "2026-05-24T00:00:01Z",
          linkedTraceCount: 1,
        },
      ],
    });
    vi.mocked(debugApi.getFlowDetail).mockReset().mockResolvedValue({
      workflowId: "wf_1",
      transitions: [
        {
          transitionId: "tr_1",
          eventType: "assistant_delegation_completed",
          status: "completed",
          fromSession: { sessionId: "child", agentType: "specialist" },
          toSession: { sessionId: "parent", agentType: "assistant" },
          reason: "done",
          detail: { output: { success: true } },
          detailProvenance: "ephemeral_debug_capture",
          detailAvailability: "full_text",
          traceIds: ["trace_done"],
          linkStatus: "linked",
          createdAt: "2026-05-24T00:00:01Z",
        },
      ],
    });
    vi.mocked(debugApi.expandReference).mockReset().mockResolvedValue({
      referenceId: "REF::msg_1",
      content: "expanded reference",
      available: true,
      truncated: false,
      nextChunk: null,
    });
  });

  test("requires warning acknowledgement before arming trace capture", async () => {
    render(<DebugScreen />);

    expect(await screen.findByText("调试记录可能包含原始用户和模型文本。")).toBeInTheDocument();
    expect(screen.getByText("开发者自行输入的秘密不会被启发式清除。")).toBeInTheDocument();
    expect(screen.getByText("停止、清空或重启会销毁当前记录。")).toBeInTheDocument();
    expect(screen.getByText("启用期间应用壳会显示持续停止入口。")).toBeInTheDocument();

    const arm = screen.getByRole("button", { name: "Enable Trace Capture" });
    expect(arm).toBeDisabled();

    fireEvent.click(screen.getByRole("checkbox", { name: /I understand the risks/ }));
    fireEvent.click(arm);

    await waitFor(() =>
      expect(debugApi.updateControl).toHaveBeenCalledWith({
        enabled: true,
        warningAcknowledged: true,
      }),
    );
    expect(await screen.findByText("ARMED")).toBeInTheDocument();
  });

  test("locates completed traces, expands flow/reference detail, and purges local state on clear", async () => {
    vi.mocked(debugApi.getControlStatus).mockResolvedValue(enabledStatus);
    render(<DebugScreen />);

    const tracePanel = await screen.findByRole("region", { name: "LLM trace records" });
    fireEvent.click(within(tracePanel).getByRole("button", { name: "Refresh" }));
    await screen.findByText("agent_loop");
    fireEvent.click(screen.getByRole("button", { name: /agent_loop/ }));
    expect(await screen.findByLabelText("Trace detail")).toHaveTextContent("safe answer");

    const flowPanel = screen.getByRole("region", { name: "Agent flow timeline" });
    fireEvent.click(within(flowPanel).getByRole("button", { name: "Refresh" }));
    await screen.findByText("wf_1");
    fireEvent.click(screen.getByRole("button", { name: /wf_1/ }));
    expect(await screen.findByText("assistant_delegation_completed")).toBeInTheDocument();
    expect(screen.getByText("completed · linked")).toBeInTheDocument();
    expect(screen.getByText("ephemeral_debug_capture · full_text")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Open trace trace_done" }));
    await waitFor(() => expect(debugApi.getTraceDetail).toHaveBeenCalledWith("trace_done"));

    fireEvent.change(screen.getByLabelText("Reference id"), { target: { value: "REF::msg_1" } });
    fireEvent.click(screen.getByRole("button", { name: "Expand" }));
    expect(await screen.findByText("expanded reference")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear" }));
    await waitFor(() => expect(debugApi.clearTraces).toHaveBeenCalled());
    expect(screen.getByText("No trace records captured in this epoch.")).toBeInTheDocument();
    expect(screen.getByText("No workflow transitions available.")).toBeInTheDocument();
    expect(screen.getByText("No reference expanded.")).toBeInTheDocument();
  });

  test("purges local raw state when the shell disables tracing", async () => {
    vi.mocked(debugApi.getControlStatus).mockResolvedValue(enabledStatus);
    render(<DebugScreen />);

    const tracePanel = await screen.findByRole("region", { name: "LLM trace records" });
    fireEvent.click(within(tracePanel).getByRole("button", { name: "Refresh" }));
    await screen.findByText("agent_loop");
    fireEvent.click(screen.getByRole("button", { name: /agent_loop/ }));
    expect(await screen.findByLabelText("Trace detail")).toHaveTextContent("safe answer");

    act(() => {
      window.dispatchEvent(new Event(debugApi.DEBUG_RAW_STATE_PURGE_EVENT));
    });

    await waitFor(() =>
      expect(screen.getByText("No trace records captured in this epoch.")).toBeInTheDocument(),
    );
    expect(screen.queryByLabelText("Trace detail")).not.toBeInTheDocument();
  });

  test("filters by session and auto-selects the newest failed trace", async () => {
    window.history.replaceState({}, "", "/debug?sessionId=ast_failed");
    vi.mocked(debugApi.getControlStatus).mockResolvedValue(enabledStatus);
    vi.mocked(debugApi.listTraces).mockResolvedValue({
      items: [
        { ...trace, traceId: "trace_failed", sessionId: "ast_failed", outcome: "failed" },
      ],
      retainedBytes: 128,
      omittedCount: 0,
      warning: "armed",
    });
    vi.mocked(debugApi.getTraceDetail).mockResolvedValue({
      ...trace,
      traceId: "trace_failed",
      sessionId: "ast_failed",
      outcome: "failed",
      inputMessages: [],
      inputMedia: [],
      inputTools: [],
      outputContent: null,
      outputToolCalls: [],
      errorSummary: "safe failure",
    });

    render(<DebugScreen />);

    expect(await screen.findByText("ast_failed")).toBeInTheDocument();
    await waitFor(() =>
      expect(debugApi.listTraces).toHaveBeenCalledWith({
        sessionId: "ast_failed",
        limit: 50,
      }),
    );
    expect(debugApi.listFlows).toHaveBeenCalledWith({
      sessionId: "ast_failed",
      limit: 20,
    });
    await waitFor(() => expect(debugApi.getTraceDetail).toHaveBeenCalledWith("trace_failed"));
    window.history.replaceState({}, "", "/debug");
  });

  test("explains that unarmed historical detail cannot be backfilled", async () => {
    window.history.replaceState({}, "", "/debug?sessionId=ast_missing");

    render(<DebugScreen />);

    expect(
      await screen.findByText(/未提前启用 trace 时，失败发生前的原始调试详情无法补录/),
    ).toBeInTheDocument();
    window.history.replaceState({}, "", "/debug");
  });
});
