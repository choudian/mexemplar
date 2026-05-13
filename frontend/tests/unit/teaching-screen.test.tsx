import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { invoke } from "@tauri-apps/api/core";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { configureDesktopApi } from "../../src/api/client";
import { TeachingScreen } from "../../src/screens/teaching/TeachingScreen";
import { useTeachingStore } from "../../src/state/teachingStore";

function jsonResponse(payload: unknown) {
  return {
    ok: true,
    json: async () => payload,
  };
}

describe("TeachingScreen", () => {
  beforeEach(() => {
    configureDesktopApi({ baseUrl: "http://desktop.test", sessionToken: "token" });
    useTeachingStore.setState({
      hydrated: false,
      readiness: [],
      selectedMode: null,
      run: null,
      stage: "selecting",
      intentReply: "",
      progressLog: [],
      busy: false,
      lastError: null,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  test("loads readiness and advances through recording, intent, and trial controls", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/teaching/readiness")) {
        return jsonResponse({
          modes: [
            { mode: "browser", status: "ready", message: "可录制浏览器操作。", actions: [] },
            { mode: "extension", status: "ready", message: "可通过浏览器扩展触发录制。", actions: [] },
            { mode: "desktop", status: "ready", message: "可录制桌面操作。", actions: [] },
          ],
        });
      }
      if (url.endsWith("/api/teaching/runs")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "selecting", summary: {} });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/recording/start")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "recording", summary: {} });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/recording/stop")) {
        return jsonResponse({
          workflowId: "rec_1",
          mode: "browser",
          stage: "intent_confirmation",
          summary: {},
        });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/intent/confirm")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "learning", summary: {} });
      }
      if (url.endsWith("/api/teaching/runs/rec_1/trial/start")) {
        return jsonResponse({ workflowId: "rec_1", mode: "browser", stage: "trial_validation", summary: {} });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<TeachingScreen />);

    await waitFor(() => expect(screen.getByText("浏览器")).toBeInTheDocument());
    fireEvent.click(screen.getAllByRole("button", { name: "开始" })[0]);
    await waitFor(() => expect(screen.getByText("开始录制")).toBeEnabled());

    fireEvent.click(screen.getByText("开始录制"));
    await waitFor(() => expect(screen.getByText("停止录制")).toBeInTheDocument());

    fireEvent.click(screen.getByText("停止录制"));
    await waitFor(() => expect(screen.getByText("确认并学习")).toBeEnabled());

    fireEvent.click(screen.getByText("确认并学习"));
    await waitFor(() => expect(screen.getByText("正在学习技能。")).toBeInTheDocument());

    act(() => {
      useTeachingStore.getState().applyEvent({
        eventId: "evt_learning_done",
        type: "teaching.progress",
        scope: { workflowId: "rec_1" },
        payload: { sourceEvent: "code_completed", headline: "Skill learning completed" },
        createdAt: "2026-05-10T00:00:00Z",
      });
    });
    await waitFor(() => expect(screen.getByText("正在验证技能。")).toBeInTheDocument());

    fireEvent.click(screen.getByText("开始试用"));
    await waitFor(() => expect(screen.getByText("正在验证技能。")).toBeInTheDocument());
  });

  test("minimizes the Tauri window before starting desktop recording", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/teaching/runs/rec_desktop/recording/start")) {
        return jsonResponse({
          workflowId: "rec_desktop",
          mode: "desktop",
          stage: "recording",
          summary: {},
        });
      }
      return jsonResponse({});
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.mocked(invoke).mockClear();
    useTeachingStore.setState({
      run: {
        workflowId: "rec_desktop",
        mode: "desktop",
        stage: "selecting",
        summary: {},
      },
      selectedMode: "desktop",
    });

    await useTeachingStore.getState().startRecording();

    expect(invoke).toHaveBeenCalledWith("minimize");
    const fetchCalls = fetchMock.mock.calls as unknown as Array<
      [RequestInfo | URL, RequestInit | undefined]
    >;
    const startCall = fetchCalls.find(([input]) =>
      String(input).endsWith("/api/teaching/runs/rec_desktop/recording/start"),
    );
    expect(startCall).toBeDefined();
    expect(JSON.parse(String((startCall?.[1] as RequestInit).body))).toEqual({
      mode: "desktop",
      windowMinimized: true,
    });
  });
});
