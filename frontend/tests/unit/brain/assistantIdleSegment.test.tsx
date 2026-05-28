import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import {
  createAssistantSession,
  decideAssistantConfirmation,
  deleteAssistantSession,
  listAssistantMessages,
  listAssistantSessions,
  renameAssistantSession,
  sendAssistantMessage,
  triggerAssistantSegmentBoundary,
  triggerAssistantSegmentIdle,
} from "../../../src/api/assistant";
import { useAssistantStore } from "../../../src/state/assistantStore";

vi.mock("../../../src/api/assistant", () => ({
  createAssistantSession: vi.fn(() => Promise.resolve("ast_new")),
  decideAssistantConfirmation: vi.fn(() => Promise.resolve({ requestId: "req_1", decision: "approve", accepted: true })),
  deleteAssistantSession: vi.fn(() => Promise.resolve()),
  listAssistantMessages: vi.fn(() => Promise.resolve({ items: [], hasMoreBefore: false, nextBeforeSequence: null })),
  listAssistantSessions: vi.fn(() => Promise.resolve([])),
  renameAssistantSession: vi.fn(),
  sendAssistantMessage: vi.fn(() => Promise.resolve({ accepted: true, sessionId: "ast_1" })),
  triggerAssistantSegmentBoundary: vi.fn(() => Promise.resolve({ segment_id: "seg-boundary", status: "pending" })),
  triggerAssistantSegmentIdle: vi.fn(() => Promise.resolve({ segment_id: "seg-1", status: "pending" })),
}));

const IDLE_THRESHOLD_MS = 123_000;

function resetAssistantStore() {
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
    pendingOptimisticMessages: [],
  });
}

describe("Assistant idle segment timer", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    resetAssistantStore();
    vi.mocked(triggerAssistantSegmentIdle).mockClear();
    vi.mocked(createAssistantSession).mockClear();
    vi.mocked(decideAssistantConfirmation).mockClear();
    vi.mocked(deleteAssistantSession).mockClear();
    vi.mocked(listAssistantMessages).mockClear();
    vi.mocked(listAssistantSessions).mockClear();
    vi.mocked(renameAssistantSession).mockClear();
    vi.mocked(sendAssistantMessage).mockClear();
    vi.mocked(triggerAssistantSegmentBoundary).mockClear();
  });

  afterEach(() => {
    resetAssistantStore();
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  test("idle timer triggers segment sealing after the threshold", async () => {
    useAssistantStore.setState({ activeSessionId: "ast_1" });
    useAssistantStore.getState().setIdleThresholdSeconds(IDLE_THRESHOLD_MS / 1000);

    useAssistantStore.getState().resetIdleTimer();
    await vi.advanceTimersByTimeAsync(IDLE_THRESHOLD_MS - 1);

    expect(triggerAssistantSegmentIdle).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(1);

    expect(triggerAssistantSegmentIdle).toHaveBeenCalledTimes(1);
    expect(triggerAssistantSegmentIdle).toHaveBeenCalledWith("ast_1");
  });

  test("restarting the idle timer collapses rapid repeated activity into one seal", async () => {
    useAssistantStore.setState({ activeSessionId: "ast_1" });
    useAssistantStore.getState().setIdleThresholdSeconds(IDLE_THRESHOLD_MS / 1000);

    useAssistantStore.getState().resetIdleTimer();
    await vi.advanceTimersByTimeAsync(60_000);
    useAssistantStore.getState().resetIdleTimer();
    await vi.advanceTimersByTimeAsync(60_000);
    useAssistantStore.getState().resetIdleTimer();
    await vi.advanceTimersByTimeAsync(IDLE_THRESHOLD_MS);

    expect(triggerAssistantSegmentIdle).toHaveBeenCalledTimes(1);
    expect(triggerAssistantSegmentIdle).toHaveBeenCalledWith("ast_1");
  });

  test("session switch resets the pending idle timer", async () => {
    useAssistantStore.setState({ activeSessionId: "ast_a" });
    useAssistantStore.getState().setIdleThresholdSeconds(IDLE_THRESHOLD_MS / 1000);
    useAssistantStore.getState().resetIdleTimer();

    await vi.advanceTimersByTimeAsync(IDLE_THRESHOLD_MS - 1_000);
    useAssistantStore.setState({ activeSessionId: "ast_b" });
    useAssistantStore.getState().resetIdleTimer();
    await vi.advanceTimersByTimeAsync(1_000);

    expect(triggerAssistantSegmentIdle).not.toHaveBeenCalled();

    await vi.advanceTimersByTimeAsync(IDLE_THRESHOLD_MS - 1_000);

    expect(triggerAssistantSegmentIdle).toHaveBeenCalledTimes(1);
    expect(triggerAssistantSegmentIdle).toHaveBeenCalledWith("ast_b");
  });

  test("clearing the idle timer prevents the pending seal", async () => {
    useAssistantStore.setState({ activeSessionId: "ast_1" });
    useAssistantStore.getState().setIdleThresholdSeconds(IDLE_THRESHOLD_MS / 1000);

    useAssistantStore.getState().resetIdleTimer();
    useAssistantStore.getState().clearIdleTimer();
    await vi.advanceTimersByTimeAsync(IDLE_THRESHOLD_MS);

    expect(triggerAssistantSegmentIdle).not.toHaveBeenCalled();
  });

  test("new sessions seal the previous conversation with a new_session boundary", async () => {
    useAssistantStore.setState({ activeSessionId: "ast_existing" });

    await useAssistantStore.getState().createSession();

    expect(triggerAssistantSegmentBoundary).toHaveBeenCalledWith("ast_existing", "new_session");
    expect(triggerAssistantSegmentIdle).not.toHaveBeenCalled();
  });

  test("selecting a different session seals the previous conversation with a new_session boundary", async () => {
    useAssistantStore.setState({ activeSessionId: "ast_existing" });

    await useAssistantStore.getState().selectSession("ast_next");

    expect(triggerAssistantSegmentBoundary).toHaveBeenCalledWith("ast_existing", "new_session");
    expect(triggerAssistantSegmentIdle).not.toHaveBeenCalled();
  });
});
