import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { AppShell } from "../../src/app/AppShell";
import * as debugApi from "../../src/api/debug";
import { useAssistantStore } from "../../src/state/assistantStore";
import { useShellStore } from "../../src/state/shellStore";
import { useTeachingStore } from "../../src/state/teachingStore";

vi.mock("../../src/api/debug", () => ({
  DEBUG_CONTROL_STATUS_EVENT: "mexemplar:debug-control-status",
  DEBUG_RAW_STATE_PURGE_EVENT: "mexemplar:debug-raw-state-purge",
  dispatchDebugControlStatus: vi.fn((status: { enabled: boolean }) => {
    window.dispatchEvent(new CustomEvent("mexemplar:debug-control-status", { detail: status }));
  }),
  dispatchDebugRawStatePurge: vi.fn(),
  getControlStatus: vi.fn(),
  updateControl: vi.fn(),
}));

const bootstrapPayload = {
  connection: {
    status: "ready",
    message: "Desktop backend is ready.",
    checks: [],
    serverTime: "2026-05-24T00:00:00Z",
  },
  user: {
    displayName: "本地用户",
    statusLabel: "本地版 · 已就绪",
  },
  navigation: {
    pendingSkillCount: 0,
    publishedSkillCount: 0,
    failureCount: 0,
    compositionCount: 0,
  },
  settingsSummary: {
    theme: "sage",
    dark: false,
    density: "comfy",
  },
  brain: {
    segmentIdleThresholdSeconds: 300,
  },
};

function jsonResponse(payload: unknown): Response {
  return {
    ok: true,
    json: async () => payload,
  } as Response;
}

function eventStreamResponse(): Response {
  return {
    ok: true,
    body: new ReadableStream(),
  } as Response;
}

function installFetchMock() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/events")) return eventStreamResponse();
      return jsonResponse(bootstrapPayload);
    }),
  );
}

describe("AppShell debug route and banner", () => {
  beforeEach(() => {
    window.history.pushState({}, "", "/");
    useShellStore.setState({
      activeRoute: "assistant",
      backend: null,
      userDisplayName: "本地用户",
      userStatusLabel: "本地版 · 启动中",
      navigation: {
        pendingSkillCount: 0,
        publishedSkillCount: 0,
        failureCount: 0,
        compositionCount: 0,
      },
    });
    useAssistantStore.getState().clearIdleTimer();
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
      idleThresholdMs: null,
    });
    useTeachingStore.setState({
      hydrated: false,
      readiness: [],
      selectedMode: null,
      run: null,
      stage: "selecting",
      progressLog: [],
      messages: [],
      toast: null,
      trialPreview: null,
      busy: false,
      lastError: null,
      skillTrialToolId: null,
      trialSuccessCount: 0,
    });
    vi.mocked(debugApi.getControlStatus).mockReset().mockResolvedValue({
      enabled: false,
      armedAt: null,
      retentionEpoch: null,
      warning: "debug warning",
      limits: { maxRecords: 200, maxRecordBytes: 1024, maxTotalBytes: 4096 },
    });
    vi.mocked(debugApi.updateControl).mockReset().mockResolvedValue({
      enabled: false,
      armedAt: null,
      retentionEpoch: null,
      warning: "debug warning",
      limits: { maxRecords: 200, maxRecordBytes: 1024, maxTotalBytes: 4096 },
    });
    vi.mocked(debugApi.dispatchDebugRawStatePurge).mockClear();
    installFetchMock();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    window.history.pushState({}, "", "/");
  });

  test("resolves hidden /debug without exposing it in ordinary navigation", async () => {
    window.history.pushState({}, "", "/debug");

    render(<AppShell />);

    expect(await screen.findByRole("heading", { name: "Debug Inspector" })).toBeInTheDocument();
    const navigation = screen.getByRole("navigation", { name: "主导航" });
    expect(within(navigation).queryByRole("button", { name: /Debug Inspector/i })).toBeNull();
  });

  test("leaves /debug through ordinary navigation and purges raw state", async () => {
    window.history.pushState({}, "", "/debug");

    render(<AppShell />);

    expect(await screen.findByRole("heading", { name: "Debug Inspector" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /AI 助手/ }));

    await waitFor(() => {
      expect(screen.queryByRole("heading", { name: "Debug Inspector" })).not.toBeInTheDocument();
    });
    expect(window.location.pathname).toBe("/");
    expect(debugApi.dispatchDebugRawStatePurge).toHaveBeenCalled();
  });

  test("shows trace-active banner and stops capture from the shell", async () => {
    vi.mocked(debugApi.getControlStatus).mockResolvedValue({
      enabled: true,
      armedAt: "2026-05-24T00:00:00Z",
      retentionEpoch: "epoch_1",
      warning: "debug warning",
      limits: { maxRecords: 200, maxRecordBytes: 1024, maxTotalBytes: 4096 },
    });

    render(<AppShell />);

    expect(await screen.findByText("Debug trace capture is active for this sidecar session.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Stop trace" }));

    await waitFor(() => expect(debugApi.updateControl).toHaveBeenCalledWith({ enabled: false }));
    expect(debugApi.dispatchDebugRawStatePurge).toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByText("Debug trace capture is active for this sidecar session.")).not.toBeInTheDocument(),
    );
  });

  test("keeps the stop banner visible when trace is armed immediately before leaving /debug", async () => {
    window.history.pushState({}, "", "/debug");
    vi.mocked(debugApi.updateControl).mockResolvedValueOnce({
      enabled: true,
      armedAt: "2026-05-24T00:00:00Z",
      retentionEpoch: "epoch_armed",
      warning: "debug warning",
      limits: { maxRecords: 200, maxRecordBytes: 1024, maxTotalBytes: 4096 },
    });

    render(<AppShell />);

    expect(await screen.findByRole("heading", { name: "Debug Inspector" })).toBeInTheDocument();
    fireEvent.click(screen.getByRole("checkbox", { name: /I understand the risks/ }));
    fireEvent.click(screen.getByRole("button", { name: "Enable Trace Capture" }));

    expect(await screen.findByText("Debug trace capture is active for this sidecar session.")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /AI 助手/ }));

    await waitFor(() => expect(window.location.pathname).toBe("/"));
    expect(screen.getByText("Debug trace capture is active for this sidecar session.")).toBeInTheDocument();
  });
});
